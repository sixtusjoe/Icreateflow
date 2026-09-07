"""Running a lead search: what it is allowed to do, and how fast.

A search is a background task, like a watched send. It expands the
operator's description into queries, browses for profiles with a discovery
account, scores what it found, and writes the results somewhere they can be
reviewed before anyone is contacted.

WHAT THIS IS
------------
Browsing, at a person's pace, for profiles the account can already see —
but a great deal of it. That is worth naming plainly: bulk collection is
against Instagram's terms and is a faster route to a restricted account
than sending messages is. Three things follow, and they are the reason the
caps below are not configurable away:

* it runs on a **discovery account**, never a sending one, so losing it
  costs a scraper rather than the account that took days to get sending;
* it is **capped per run and per day**, and the cap is meant to be tuned
  down when a platform pushes back, not up;
* it **pauses between profiles**, because going slowly is most of what
  keeps it unremarkable.

Nothing here logs in, follows, likes, comments or messages. It reads.
"""
from __future__ import annotations

import asyncio
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

import database as db
from services.outreach import config as cfg
from services.outreach import lead_ai, local_browser
from services.outreach.browser import get_driver
from services.outreach.constants import ACCOUNT_PURPOSE_DISCOVERY
from services.outreach.crypto import decrypt_session

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

#: Which driver discovers for which platform. TikTok's is absent on
#: purpose: nobody has written its discovery selectors, and pretending
#: otherwise would fail deep inside a run rather than at the start.
PLATFORM_DRIVERS = {"instagram": "playwright_instagram"}


@dataclass
class Run:
    """A search in flight, as the import dialog needs to see it."""

    search_id: int
    status: str = STATUS_QUEUED
    message: str = "Working out what to search for…"
    found: int = 0
    wanted: int = 0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str] = None

    @property
    def done(self) -> bool:
        return self.status in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_id": self.search_id,
            "status": self.status,
            "message": self.message,
            "found": self.found,
            "wanted": self.wanted,
            "done": self.done,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_RUNS: dict[int, Run] = {}
_TASKS: dict[int, asyncio.Task] = {}
_CANCELLED: set[int] = set()


def unavailable_reason() -> Optional[str]:
    return local_browser.unavailable_reason("Lead discovery")


def status_for(search_id: int) -> Optional[Run]:
    return _RUNS.get(int(search_id))


def is_running(search_id: int) -> bool:
    task = _TASKS.get(int(search_id))
    return task is not None and not task.done()


def any_running() -> bool:
    return any(t is not None and not t.done() for t in _TASKS.values())


def cancel(search_id: int) -> bool:
    """Ask a run to stop at its next profile. Returns whether it was live."""
    if not is_running(search_id):
        return False
    _CANCELLED.add(int(search_id))
    return True


async def visited_today(database, account_id: int) -> int:
    """Profiles this account has opened in the last 24 hours.

    Counted from the searches themselves rather than a counter, so a crash
    mid-run cannot lose the count and let the cap be exceeded by restarting.
    """
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    row = (await database.session.execute(
        text(
            "SELECT COALESCE(SUM(visited), 0) FROM outreach_lead_searches "
            " WHERE account_id = :aid AND started_at IS NOT NULL "
            "   AND started_at >= :since"
        ),
        {"aid": int(account_id), "since": since},
    )).first()
    return int(row[0] or 0) if row else 0


async def discovery_accounts(database, platform: str, user_id: Optional[int]) -> list[dict]:
    """Accounts marked for discovery on this platform, with a session."""
    rows = await db.get_sending_accounts(database, user_id=user_id)
    return [
        dict(r) for r in rows
        if (dict(r).get("purpose") == ACCOUNT_PURPOSE_DISCOVERY
            and dict(r).get("platform") == platform
            and dict(r).get("session_state_encrypted")
            and dict(r).get("enabled"))
    ]


def start(search: dict[str, Any], account: dict[str, Any], settings: dict[str, Any]) -> Run:
    """Begin a search. Returns immediately; poll `status_for`.

    Raises ValueError when another search is already browsing — two of
    these at once is twice the footprint for no more speed, and they would
    be sharing one account's session.
    """
    search_id = int(search["id"])
    if any_running():
        raise ValueError("A lead search is already running. Wait for it to finish.")

    run = Run(search_id=search_id, wanted=int(search.get("wanted") or 0))
    _RUNS[search_id] = run
    _CANCELLED.discard(search_id)
    _TASKS[search_id] = asyncio.create_task(_run(search, account, settings, run))
    return run


async def _run(search: dict[str, Any], account: dict[str, Any],
               settings: dict[str, Any], run: Run) -> None:
    search_id = int(search["id"])
    platform = (search.get("platform") or "instagram").lower()
    user_id = search.get("user_id")

    def finish(status: str, message: str) -> None:
        run.status = status
        run.message = message
        run.finished_at = datetime.now(timezone.utc).isoformat()

    driver = None
    visited = 0
    try:
        driver_name = PLATFORM_DRIVERS.get(platform)
        if not driver_name:
            finish(STATUS_FAILED, f"No discovery driver for {platform}.")
            await _persist_status(search_id, STATUS_FAILED, run.message, 0, 0)
            return

        # --- caps, before anything opens a browser ---------------------
        database = await db.get_db()
        try:
            per_search = int(settings["outreach_discovery_max_per_search"])
            daily_cap = int(settings["outreach_discovery_daily_cap"])
            already = await visited_today(database, int(account["id"]))
            remaining_today = max(daily_cap - already, 0)
            if remaining_today <= 0:
                finish(
                    STATUS_FAILED,
                    f"This account has already opened {already} profiles in the "
                    f"last 24 hours — the cap is {daily_cap}. Try tomorrow, or "
                    f"raise the cap in settings if you are sure.",
                )
                await _persist_status(search_id, STATUS_FAILED, run.message, 0, 0)
                return

            wanted = min(int(search.get("wanted") or 50), per_search, remaining_today)
            run.wanted = wanted

            # --- what to search for ------------------------------------
            run.status = STATUS_RUNNING
            run.message = "Working out what to search for…"
            await _persist_status(search_id, STATUS_RUNNING, run.message, 0, 0,
                                  started=True)
            plan = await lead_ai.expand_query(
                database, search.get("niche") or "", search.get("location") or "",
                search.get("interests") or "", platform=platform, user_id=user_id,
            )
        finally:
            await database.close()

        await _persist_queries(search_id, plan)
        run.message = (
            f"Searching {len(plan['hashtags'])} hashtag(s) and "
            f"{len(plan['terms'])} term(s)…"
        )

        # --- browse ----------------------------------------------------
        payload = {
            "id": int(account["id"]),
            "name": account.get("name"),
            "platform": platform,
            "session_state": decrypt_session(account.get("session_state_encrypted")),
        }
        driver = get_driver(driver_name, headless=False)
        await driver.startup()

        collected: list[dict[str, Any]] = []

        async def on_found(lead: dict[str, Any]) -> None:
            collected.append(lead)
            run.found = len(collected)
            run.message = f"Found {len(collected)} of {wanted}…"

        leads = await driver.discover_profiles(
            payload,
            hashtags=tuple(plan["hashtags"]),
            terms=tuple(plan["terms"]),
            limit=wanted,
            include_commenters=bool(search.get("include_commenters")),
            include_likers=bool(search.get("include_likers")),
            interval_seconds=float(settings["outreach_discovery_interval_seconds"]),
            scroll_rounds=int(settings["outreach_discovery_scroll_rounds"]),
            should_stop=lambda: search_id in _CANCELLED,
            on_found=on_found,
        )
        visited = len(leads)

        # --- score and store -------------------------------------------
        run.message = f"Scoring {len(leads)} profile(s)…"
        database = await db.get_db()
        try:
            leads = await lead_ai.score_leads(
                database, leads, search.get("niche") or "",
                search.get("location") or "", search.get("interests") or "",
                user_id=user_id,
            )
            stored = await _store_leads(database, search_id, user_id, platform, leads)
        finally:
            await database.close()

        run.found = stored
        if search_id in _CANCELLED:
            finish(STATUS_CANCELLED, f"Stopped early — {stored} profile(s) kept.")
            await _persist_status(search_id, STATUS_CANCELLED, run.message, stored, visited)
            return

        finish(
            STATUS_DONE,
            f"Found {stored} profile(s). Review them and import the ones you want."
            if stored else
            "No profiles found. Try a broader niche, or different wording.",
        )
        await _persist_status(search_id, STATUS_DONE, run.message, stored, visited)
    except asyncio.CancelledError:
        finish(STATUS_CANCELLED, "The search was cancelled.")
        await _persist_status(search_id, STATUS_CANCELLED, run.message, run.found, visited)
        raise
    except Exception as exc:  # noqa: BLE001 — the dialog has to hear about it
        traceback.print_exc()
        finish(STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:300])
        await _persist_status(search_id, STATUS_FAILED, run.message, run.found, visited)
    finally:
        _CANCELLED.discard(search_id)
        if driver is not None:
            try:
                await driver.shutdown()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                traceback.print_exc()


async def _persist_status(search_id: int, status: str, message: str,
                          found: int, visited: int, started: bool = False) -> None:
    database = await db.get_db()
    try:
        sets = ["status = :status", "message = :message", "found = :found",
                "visited = :visited", "updated_at = NOW()"]
        params = {"id": search_id, "status": status, "message": message[:1000],
                  "found": found, "visited": visited}
        if started:
            sets.append("started_at = NOW()")
        if status in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED):
            sets.append("finished_at = NOW()")
        await database.session.execute(
            text(f"UPDATE outreach_lead_searches SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        await database.session.commit()
    except Exception:  # noqa: BLE001 — status is reporting, not the work
        traceback.print_exc()
    finally:
        await database.close()


async def _persist_queries(search_id: int, plan: dict[str, list[str]]) -> None:
    database = await db.get_db()
    try:
        await database.session.execute(
            text("UPDATE outreach_lead_searches SET queries = :q WHERE id = :id"),
            {"id": search_id, "q": json.dumps(plan)},
        )
        await database.session.commit()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    finally:
        await database.close()


async def _store_leads(database, search_id: int, user_id: Optional[int],
                       platform: str, leads: list[dict[str, Any]]) -> int:
    """Write what was found. Duplicates within a search are dropped."""
    stored = 0
    for lead in leads:
        try:
            await database.session.execute(
                text(
                    "INSERT INTO outreach_leads "
                    "  (search_id, user_id, platform, username, profile_url, "
                    "   display_name, bio, followers, source, score, reason) "
                    "VALUES (:sid, :uid, :platform, :username, :url, :name, "
                    "        :bio, :followers, :source, :score, :reason) "
                    "ON CONFLICT (search_id, username) DO NOTHING"
                ),
                {
                    "sid": search_id, "uid": user_id, "platform": platform,
                    "username": lead["username"], "url": lead["profile_url"],
                    "name": lead.get("display_name"), "bio": lead.get("bio"),
                    "followers": lead.get("followers"), "source": lead.get("source"),
                    "score": lead.get("score"), "reason": lead.get("reason"),
                },
            )
            stored += 1
        except Exception:  # noqa: BLE001 — one bad row must not lose the rest
            traceback.print_exc()
    await database.session.commit()
    return stored
