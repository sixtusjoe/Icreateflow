"""Reading a post's commenters over HTTP, with no DOM anywhere.

The browser appears once, to mint a signature, and never touches the
reading. What that buys, measured 2026-09-22: 779 people from a
1,637-comment post in about two minutes, against `memory.md`'s "a read of
one post takes hours" for the DOM reader.

Three things here are not optional, and each one is a measured failure
rather than a precaution:

* **An empty 200 is a failure, never an end.** It is the normal way this
  endpoint fails, and a reader that treats it as "no more comments" reports
  a partial read as a complete one.
* **`has_more=0` at cursor 1000 is a cap, not the end.** It looks like a
  clean finish and is not one.
* **A read costs the account.** ~700 requests on one account had it served
  empty responses in its own browser for about a day. The budget is part of
  the reader, not something a caller is trusted to remember.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from services.outreach.constants import (
    RESULT_BROWSER_ERROR,
    RESULT_EMPTY_RESPONSE,
    RESULT_RATE_LIMITED,
    RESULT_SENT,
    RESULT_SESSION_EXPIRED,
    RESULT_UNKNOWN,
)
from services.outreach.net.result import LeadRow, ReadResult
from services.outreach.net.session import ReadSession
from services.outreach.net.tiktok import endpoints, parse

#: How many requests one minted signature is expected to serve. Observed 35
#: and 16 before expiry, so this is a ceiling for accounting rather than a
#: promise — the read re-mints when a request comes back empty, whenever
#: that happens to be.
REQUESTS_PER_MINT_HINT = 30

#: How many times a read will mint a fresh signature before giving up. A
#: read that needs more than this is not paging, it is being refused.
MAX_MINTS = 8


class Minted:
    """One signed request, as the page itself made it.

    The reader never builds a signature. It takes a request the browser
    made and changes only the cursor — measured: the signature does not
    cover `cursor`, and one mint pages until it expires.
    """

    def __init__(self, url: str, headers: dict[str, str], cookies: dict[str, str]):
        parsed = urlparse(url)
        self.base = parsed
        self.params: dict[str, str] = {
            k: v[0] for k, v in parse_qs(parsed.query).items()
        }
        self.headers = {
            k: v for k, v in (headers or {}).items()
            if k.lower() not in ("cookie", "content-length", "host",
                                 ":authority", ":method", ":path", ":scheme")
        }
        self.cookies = dict(cookies or {})

    def url_for(self, path: Optional[str] = None, **overrides: Any) -> str:
        params = dict(self.params)
        params.update({k: str(v) for k, v in overrides.items() if v is not None})
        target = self.base._replace(query=urlencode(params))
        if path:
            target = target._replace(path=path)
        return urlunparse(target)


def _classify(response) -> tuple[str, Optional[dict[str, Any]]]:
    """(status, payload). A payload only when the read may continue."""
    if response.status_code == 429:
        return RESULT_RATE_LIMITED, None
    if response.status_code in (401, 403):
        return RESULT_SESSION_EXPIRED, None
    if response.status_code != 200:
        return RESULT_UNKNOWN, None
    if not response.text:
        # The one that matters. No code, no message, nothing — and both an
        # expired signature and a throttled account look like this.
        return RESULT_EMPTY_RESPONSE, None
    try:
        payload = response.json()
    except ValueError:
        return RESULT_UNKNOWN, None
    if payload.get("status_code") not in (0, None):
        return RESULT_RATE_LIMITED, payload
    return RESULT_SENT, payload


async def read_commenters(
    post_url: str,
    *,
    mint: Callable[[], Awaitable[Minted]],
    request_budget: int = 200,
    include_replies: bool = True,
    page_size: int = endpoints.PAGE_SIZE,
    delay_seconds: float = 0.6,
    on_found: Optional[Callable[[LeadRow], None]] = None,
    exclude: Optional[Iterable[str]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ReadResult:
    """Everyone who commented on one post, root comments and reply threads.

    `mint` is called for the first signature and again whenever one dies.
    `request_budget` is the account's, not the post's: it is spent across
    both phases and a read stops when it runs out, with what it has.
    """
    item_id = endpoints.post_id_from_url(post_url)
    if not item_id:
        return ReadResult(False, RESULT_UNKNOWN, error=f"Not a post URL: {post_url!r}")

    skip = {str(x).lower() for x in (exclude or ())}
    rows: list[LeadRow] = []
    seen: set[str] = set()
    threads: list[tuple[str, int]] = []
    spent = 0
    mints = 0
    claimed_total: Any = None
    hit_cap = False
    exhausted = False

    def keep(found: list[LeadRow]) -> None:
        for row in found:
            if row.username.lower() in skip or row.username in seen:
                continue
            seen.add(row.username)
            rows.append(row)
            if on_found is not None:
                # Banked as it is found, not when the read ends: a read that
                # stops part-way has still done the work.
                on_found(row)

    try:
        current = await mint()
    except Exception as exc:  # noqa: BLE001 — a mint failure is a read failure
        return ReadResult(
            False, RESULT_BROWSER_ERROR,
            error=f"No signature could be minted: {type(exc).__name__}: {exc}",
            detail={"requests": 0, "mints": 0, "exhausted": False})
    mints = 1
    async with ReadSession(current.cookies, headers=current.headers) as session:

        async def fetch(url: str) -> tuple[str, Optional[dict[str, Any]]]:
            nonlocal spent
            spent += 1
            return _classify(await session.get(url))

        async def remint() -> bool:
            """A fresh signature, or False when the budget is spent."""
            nonlocal current, mints
            if mints >= MAX_MINTS:
                return False
            try:
                current = await mint()
            except Exception as exc:  # noqa: BLE001
                # The browser could not produce another signature — the
                # page may no longer be served comments at all. That ends
                # the read, but the rows already collected are real and are
                # handed back by the caller.
                print(f"[net.tiktok] re-mint failed: "
                      f"{type(exc).__name__}: {exc}", flush=True)
                return False
            mints += 1
            session.replace_headers(current.headers)
            return True

        # --- phase 1: root comments -----------------------------------
        cursor = 0
        while spent < request_budget:
            if should_stop is not None and should_stop():
                break
            status, payload = await fetch(current.url_for(
                **{endpoints.AWEME_ID: item_id,
                   endpoints.CURSOR: cursor,
                   endpoints.COUNT: page_size}))

            if status == RESULT_EMPTY_RESPONSE:
                if await remint():
                    continue
                return ReadResult(
                    False, RESULT_EMPTY_RESPONSE, rows=rows,
                    error=("The endpoint returned HTTP 200 with an empty body "
                           "and a fresh signature did not help — this is not "
                           "an empty comment list"),
                    detail=_detail(spent, mints, cursor, claimed_total,
                                   hit_cap, exhausted, len(threads)))
            if status != RESULT_SENT or payload is None:
                return ReadResult(
                    False, status, rows=rows,
                    error=f"Reading {post_url} stopped: {status}",
                    detail=_detail(spent, mints, cursor, claimed_total,
                                   hit_cap, exhausted, len(threads)))

            keep(parse.leads_from_comments(payload, source=post_url))
            threads.extend(parse.threads_with_replies(payload))
            state = parse.page_state(payload)
            claimed_total = state["claimed_total"]

            if not state["has_more"]:
                # `has_more=0` at the cap is the platform declining to page
                # further, not the end of the comments. Saying "complete"
                # here is the mistake this reader exists to avoid.
                hit_cap = cursor >= endpoints.COMMENT_ROOT_CAP - page_size
                exhausted = not hit_cap
                break
            nxt = state["cursor"]
            if nxt is None or nxt == cursor:
                break
            cursor = int(nxt)
            await sleep(delay_seconds)

        # --- phase 2: reply threads -----------------------------------
        if include_replies:
            for cid, _count in threads:
                if spent >= request_budget:
                    exhausted = False
                    break
                if should_stop is not None and should_stop():
                    exhausted = False
                    break
                reply_cursor = 0
                while spent < request_budget:
                    status, payload = await fetch(current.url_for(
                        path=urlparse(endpoints.COMMENT_REPLY_LIST).path,
                        **{endpoints.COMMENT_ID: cid,
                           endpoints.ITEM_ID: item_id,
                           endpoints.CURSOR: reply_cursor,
                           endpoints.COUNT: page_size}))
                    if status == RESULT_EMPTY_RESPONSE:
                        if await remint():
                            continue
                        # The root read already succeeded; report what we
                        # have rather than throwing it away.
                        return ReadResult(
                            False, RESULT_EMPTY_RESPONSE, rows=rows,
                            error="A reply thread returned an empty 200",
                            detail=_detail(spent, mints, cursor, claimed_total,
                                           hit_cap, False, len(threads)))
                    if status != RESULT_SENT or payload is None:
                        break
                    keep(parse.leads_from_comments(payload, source=post_url))
                    state = parse.page_state(payload)
                    if not state["has_more"]:
                        break
                    nxt = state["cursor"]
                    if nxt is None or nxt == reply_cursor:
                        break
                    reply_cursor = int(nxt)
                    await sleep(delay_seconds)

    return ReadResult(
        True, RESULT_SENT, rows=rows,
        detail=_detail(spent, mints, cursor, claimed_total, hit_cap,
                       exhausted, len(threads)))


def _detail(spent, mints, cursor, claimed_total, hit_cap, exhausted, threads):
    return {
        "requests": spent,
        "mints": mints,
        "cursor": cursor,
        # The platform's claim, not a target: it counts replies and deleted
        # comments the root list will never return.
        "claimed_total": claimed_total,
        "hit_root_cap": hit_cap,
        "exhausted": exhausted,
        "reply_threads": threads,
    }
