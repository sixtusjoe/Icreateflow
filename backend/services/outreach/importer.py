"""Target import — CSV / pasted list → validated `outreach_targets` rows.

Validation happens before anything is inserted, and dedup happens twice:
once in Python against the rest of the batch plus the campaign's existing
targets, and once in Postgres via the `(campaign_id, username)` unique
constraint. The second one is what makes two simultaneous imports of the
same file safe.

The parser is intentionally forgiving about *shape* (column order, a bare
list of usernames, `@handle`, a full profile URL with query junk) and
strict about *content* — an entry that can't be resolved to a real
username + a URL on the platform's own domain is reported as invalid
rather than guessed at.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlparse, unquote

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import OutreachTarget
from services.outreach.stats import refresh_campaign_totals

#: Per platform: the hostnames we accept, and how to build a profile URL.
PLATFORMS: dict[str, dict[str, Any]] = {
    "tiktok": {
        "hosts": ("tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com"),
        "profile": "https://www.tiktok.com/@{username}",
        # TikTok handles: 2-24 of letters/digits/underscore/period.
        "username_re": re.compile(r"^[A-Za-z0-9_.]{2,24}$"),
    },
}

DEFAULT_PLATFORM = "tiktok"

#: Guard against someone pasting a 200 MB file into the import box.
MAX_ROWS = 100_000
MAX_BYTES = 20 * 1024 * 1024

USERNAME_HEADERS = ("username", "user", "handle", "user_name", "account", "name")
URL_HEADERS = ("profile_url", "url", "profile", "link", "profileurl", "profile url")


class ImportError_(ValueError):
    """The batch itself is unusable (too big, undecodable, unknown platform)."""


def _platform_spec(platform: str) -> dict[str, Any]:
    spec = PLATFORMS.get((platform or "").lower())
    if not spec:
        raise ImportError_(f"Unsupported platform: {platform!r}")
    return spec


def normalize_username(raw: Optional[str]) -> str:
    """`@Handle ` → `handle`. Empty string when there's nothing usable."""
    value = (raw or "").strip().lstrip("@").strip()
    return value.lower()


def username_from_url(url: str, platform: str = DEFAULT_PLATFORM) -> Optional[str]:
    """Pull the handle out of a profile URL, or None if it isn't one.

    Rejects any host outside the platform's own domains — that check is
    what stops an imported CSV from pointing the browser worker at an
    attacker-chosen site.
    """
    spec = _platform_spec(platform)
    candidate = (url or "").strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in spec["hosts"]:
        return None
    # /@handle, /@handle/video/123, or a bare /handle on the short domain.
    path = unquote(parsed.path or "").strip("/")
    if not path:
        return None
    first = path.split("/")[0]
    handle = normalize_username(first)
    if not handle or not spec["username_re"].match(handle):
        return None
    return handle


def profile_url_for(username: str, platform: str = DEFAULT_PLATFORM) -> str:
    return _platform_spec(platform)["profile"].format(username=username)


def validate_entry(
    username: Optional[str],
    profile_url: Optional[str],
    platform: str = DEFAULT_PLATFORM,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve one entry to `(username, profile_url, error)`.

    Either field alone is enough: a URL yields the username, a username
    yields the canonical URL. When both are present they must agree —
    a mismatch is an error rather than a silent pick, because picking
    wrong means messaging the wrong person.
    """
    spec = _platform_spec(platform)
    uname = normalize_username(username)
    url = (profile_url or "").strip()

    url_handle = username_from_url(url, platform) if url else None
    if url and url_handle is None:
        return None, None, f"Invalid {platform} profile URL: {url[:120]}"

    # A bare username column holding a URL is common in exported sheets.
    if uname and not url and ("/" in uname or "." in uname and " " not in uname):
        maybe = username_from_url(username or "", platform)
        if maybe:
            uname, url_handle, url = maybe, maybe, (username or "").strip()

    if not uname and url_handle:
        uname = url_handle
    if not uname:
        return None, None, "Missing username and profile URL"
    if not spec["username_re"].match(uname):
        return None, None, f"Invalid username: {(username or uname)[:60]}"
    if url_handle and url_handle != uname:
        return None, None, f"Username {uname!r} does not match profile URL {url[:120]}"

    return uname, (url if url_handle else profile_url_for(uname, platform)), None


def _pick(header: list[str], candidates: Iterable[str]) -> Optional[int]:
    lowered = [h.strip().lower().lstrip("﻿") for h in header]
    for name in candidates:
        if name in lowered:
            return lowered.index(name)
    return None


def parse_csv(content: str | bytes, platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    """Parse CSV text (or a newline-separated list) into entries.

    Returns `{"entries": [...], "invalid": [{"line", "value", "reason"}]}`.
    Nothing is written — `import_targets` does that.
    """
    if isinstance(content, bytes):
        if len(content) > MAX_BYTES:
            raise ImportError_("File is too large (limit 20 MB)")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 can't fail
                raise ImportError_("File is not valid text") from exc
    else:
        text = content
    if len(text) > MAX_BYTES:
        raise ImportError_("File is too large (limit 20 MB)")

    _platform_spec(platform)  # fail fast on an unknown platform

    rows = list(csv.reader(io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n"))))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return {"entries": [], "invalid": []}

    header = rows[0]
    uname_idx = _pick(header, USERNAME_HEADERS)
    url_idx = _pick(header, URL_HEADERS)
    if uname_idx is None and url_idx is None:
        # Headerless: one column is a username, two is username,profile_url.
        data_rows, uname_idx, url_idx = rows, 0, (1 if len(header) > 1 else None)
    else:
        data_rows = rows[1:]

    if len(data_rows) > MAX_ROWS:
        raise ImportError_(f"Too many rows (limit {MAX_ROWS:,})")

    entries: list[dict[str, str]] = []
    invalid: list[dict[str, Any]] = []
    for offset, row in enumerate(data_rows):
        line = offset + (1 if data_rows is rows else 2)

        def cell(idx: Optional[int]) -> Optional[str]:
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        raw_user, raw_url = cell(uname_idx), cell(url_idx)
        username, url, error = validate_entry(raw_user, raw_url, platform)
        if error:
            invalid.append({
                "line": line,
                "value": " ".join(str(c) for c in row if c)[:160],
                "reason": error,
            })
            continue
        entries.append({"username": username, "profile_url": url})

    return {"entries": entries, "invalid": invalid}


async def import_targets(
    database,
    campaign_id: int,
    content: str | bytes,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, Any]:
    """Parse, dedupe and insert. Returns the summary shown after an import.

        {"imported": 1000, "duplicates": 25, "invalid": 7, "ready": 968, ...}

    `imported` counts the rows read from the file, `ready` the rows that
    actually landed in the campaign — matching how the summary reads to a
    person looking at their own CSV.
    """
    parsed = parse_csv(content, platform)
    entries: list[dict[str, str]] = parsed["entries"]
    invalid: list[dict[str, Any]] = parsed["invalid"]
    rows_read = len(entries) + len(invalid)

    session = database.session
    existing = set(
        (await session.execute(
            select(OutreachTarget.username).where(OutreachTarget.campaign_id == campaign_id)
        )).scalars().all()
    )

    seen: set[str] = set()
    fresh: list[dict[str, str]] = []
    duplicates = 0
    for entry in entries:
        name = entry["username"]
        if name in existing or name in seen:
            duplicates += 1
            continue
        seen.add(name)
        fresh.append(entry)

    inserted = 0
    if fresh:
        # ON CONFLICT DO NOTHING covers the race the Python dedup can't:
        # two imports of the same list running at the same moment.
        result = await session.execute(
            pg_insert(OutreachTarget)
            .values([
                {
                    "campaign_id": campaign_id,
                    "username": e["username"],
                    "profile_url": e["profile_url"],
                    "status": "queued",
                }
                for e in fresh
            ])
            .on_conflict_do_nothing(constraint="outreach_targets_campaign_username_uq")
            .returning(OutreachTarget.id)
        )
        inserted = len(result.scalars().all())
        await session.commit()
        # Rows the constraint rejected were duplicates too.
        duplicates += len(fresh) - inserted

    await refresh_campaign_totals(database, campaign_id)

    return {
        "imported": rows_read,
        "duplicates": duplicates,
        "invalid": len(invalid),
        "ready": inserted,
        # Cap the detail list — a 100k-row file with every row broken should
        # not return a 100k-entry payload.
        "invalid_rows": invalid[:100],
        "invalid_truncated": max(0, len(invalid) - 100),
    }
