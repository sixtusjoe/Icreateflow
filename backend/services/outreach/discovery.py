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
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import text

import database as db
from services.outreach import config as cfg
from services.outreach import lead_ai, local_browser
from services.outreach import display_pool
from services.outreach.browser import discovery_needs_headed, get_driver
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
PLATFORM_DRIVERS = {
    "instagram": "playwright_instagram",
    "x": "playwright_x",
    "tiktok": "playwright_tiktok",
}

#: A seed that is a link to a post rather than an account. Handing the
#: search specific videos is a different job from searching for them.
#:
#: The short forms matter more than they look. TikTok's own "Copy link" in
#: the app gives `vt.tiktok.com/<code>` — and only `tiktok.com/t/<code>`
#: was matched here, so the link most people actually paste fell through to
#: the account branch: discovery read it as a *handle*, went looking for
#: that account's followers, found nothing, and reported "No profiles
#: found. Try a broader niche, or different wording." Which cannot work,
#: because there was nothing wrong with the niche.
#:
#: Both short hosts are real and both are in circulation — `vm` is the
#: older one, `vt` is what the app hands out now.
SHORT_LINK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_POST_URL = re.compile(
    r"https?://\S*/(video|reel|p|status)/"
    r"|tiktok\.com/t/"
    r"|https?://(?:vt|vm)\.tiktok\.com/[\w-]+",
    re.I,
)


#: An Instagram post link, however it was copied. The share sheet gives
#: /reel/<code>/?stkn=…, and that form does not stay put: Instagram
#: redirects it to /reels/<code>/, which is the scrolling feed viewer —
#: a different post every few seconds and no comment section at all.
#: Verified 2026-09-20: the reader opened it, found no comments because
#: there were none to find, and the search ended "No profiles found".
#: The /p/<code>/ form serves the single post with its comments and does
#: not redirect.
_IG_POST = re.compile(
    r"^https?://(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/([\w-]+)", re.I
)


def canonical_post_url(url: str) -> str:
    """The form of this link that actually shows the post and its comments.

    Only Instagram needs rewriting today; every other platform's post
    link is left exactly as it was given.
    """
    match = _IG_POST.match((url or "").strip())
    if not match:
        return (url or "").strip()
    # The share token is what the redirect keys off, so it goes too.
    return f"https://www.instagram.com/p/{match.group(1)}/"


#: TikTok's share-sheet links, which hide the real post behind a redirect.
_TIKTOK_SHORT = re.compile(r"^https?://(?:vt|vm)\.tiktok\.com/[\w-]+", re.I)


def post_urls_in(seeds: list[str]) -> list[str]:
    """The seeds that are links to posts, not account names."""
    return [canonical_post_url(s) for s in seeds if _POST_URL.search(s or "")]


async def expand_short_links(urls: list[str]) -> list[str]:
    """Follow TikTok's share links to the post they actually point at.

    The browser would follow the redirect by itself, so this is not what
    makes the read work. It is what makes two spellings of one post the
    same post: a run seeded with `vt.tiktok.com/ZSbejH26F` and one seeded
    with the full `/@kjlyrics/video/7639669277162769685` are otherwise two
    different posts to everything that remembers which have been read, and
    a post that is used up gets harvested again for nothing.

    Failure is not fatal — an unresolved link is handed on as it came, and
    the browser still follows it.
    """
    out: list[str] = []
    for url in urls:
        if not _TIKTOK_SHORT.match(url or ""):
            out.append(url)
            continue
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15,
                headers={"user-agent": SHORT_LINK_USER_AGENT},
            ) as client:
                response = await client.get(url)
            resolved = str(response.url).split("?", 1)[0]
            if _POST_URL.search(resolved):
                print(f"[outreach] seed {url} -> {resolved}", flush=True)
                out.append(resolved)
                continue
        except Exception as exc:  # noqa: BLE001 — a seed is not worth failing on
            print(f"[outreach] could not expand {url}: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        out.append(url)
    return out


#: How often a running search writes its progress. Reporting, not work —
#: often enough that the dashboard moves, rarely enough that it costs
#: nothing next to a page load per profile.
PROGRESS_EVERY_SECONDS = float(
    os.environ.get("ICREATE_DISCOVERY_PROGRESS_SECONDS", "5")
)


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
#: search_id → the discovery account it browses as. One account never runs
#: two searches: they would share its session and look like one person in
#: two places at once.
_ACCOUNT_OF: dict[int, int] = {}


def _started(run: "Run") -> datetime:
    try:
        return datetime.fromisoformat(run.started_at)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


#: A link to someone's profile rather than to a post: the handle is the
#: first part of the path (TikTok's with an "@").
_PROFILE_URL = re.compile(
    r"^(?:https?://)?(?:www\.|m\.|mobile\.)?"
    r"(?:x\.com|twitter\.com|tiktok\.com|instagram\.com)/@?([\w.]+)",
    re.I,
)


def _seed(part: str) -> str:
    """One seed as the readers want it: a handle, or a post link untouched.

    A pasted profile link used to go through as the "handle" — X's share
    sheet gives `https://x.com/allergictoguac?s=11`, and the run went
    looking for a user called that, found nothing and said so only as
    "0 recent posts" (2026-09-27, search 46).
    """
    part = part.strip()
    if _POST_URL.search(part):
        return part
    match = _PROFILE_URL.match(part)
    if match:
        return match.group(1)
    return part.lstrip("@")


def _seed_list(raw: Optional[str]) -> list[str]:
    """"@one, two, https://x.com/three?s=11" -> ["one", "two", "three"]."""
    if not raw:
        return []
    parts = [_seed(p) for p in str(raw).replace("\n", ",").split(",")]
    return [p for p in parts if p][:10]


def unavailable_reason() -> Optional[str]:
    return local_browser.unavailable_reason("Lead discovery")


def status_for(search_id: int) -> Optional[Run]:
    return _RUNS.get(int(search_id))


def is_running(search_id: int) -> bool:
    task = _TASKS.get(int(search_id))
    return task is not None and not task.done()


def any_running() -> bool:
    return any(t is not None and not t.done() for t in _TASKS.values())


def running_count() -> int:
    return sum(1 for t in _TASKS.values() if t is not None and not t.done())


def busy_account_ids() -> set[int]:
    """Discovery accounts in the middle of a search right now."""
    return {aid for sid, aid in _ACCOUNT_OF.items() if is_running(sid)}


def why_not_now(accounts: list[dict[str, Any]], settings: dict[str, Any]) -> Optional[str]:
    """Why no new search can start this moment, or None if one can."""
    limit = int(settings["outreach_discovery_max_concurrent"])
    if running_count() >= limit:
        return (f"{limit} search{'es are' if limit != 1 else ' is'} already running, "
                f"the most this server runs at once. Wait for one to finish.")
    busy = busy_account_ids()
    if accounts and all(int(a["id"]) in busy for a in accounts):
        return ("Every discovery account is already running a search. Wait for "
                "one to finish, or add another discovery account.")
    return None


#: How long a cancelled run is given to stop by itself before the task is
#: cancelled outright. Cooperative first, because a run that stops at its
#: own next checkpoint keeps the profiles it has already found.
CANCEL_GRACE_SECONDS = float(os.environ.get("ICREATE_OUTREACH_CANCEL_GRACE", "8"))


async def _hard_cancel_after_grace(search_id: int) -> None:
    """Cancel the task outright if asking nicely did not work.

    The flag is only read between profiles, and a run can be inside one
    operation for a very long time — the silence backstop on a hungry list
    is sixty minutes. So "Stop" looked like it did nothing at all, because
    from outside it is indistinguishable from doing nothing.

    `_run` already handles `CancelledError`: it marks the search cancelled
    and its `finally` shuts the browser down, so this loses nothing except
    the profiles that operation would have returned.
    """
    try:
        await asyncio.sleep(CANCEL_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    task = _TASKS.get(int(search_id))
    if task is not None and not task.done():
        print(f"[outreach] search {search_id} did not stop within "
              f"{CANCEL_GRACE_SECONDS:.0f}s — cancelling it outright",
              flush=True)
        task.cancel()


def cancel(search_id: int) -> bool:
    """Stop a run. Returns whether there was a live task to stop.

    Asks first and insists second. The caller must not depend on the return
    value to decide whether the *search* was stopped — a row can say
    `running` with no task behind it, and the endpoint marks those stopped
    itself rather than leaving them running forever.
    """
    search_id = int(search_id)
    # Set the flag even when no task is found: it costs nothing, and a task
    # that is mid-await when this is called still reads it afterwards.
    _CANCELLED.add(search_id)
    if not is_running(search_id):
        return False
    try:
        asyncio.get_running_loop().create_task(_hard_cancel_after_grace(search_id))
    except RuntimeError:
        # No loop here (a synchronous caller); the cooperative flag stands.
        pass
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


async def already_known(database, user_id: Optional[int], platform: str) -> set[str]:
    """Everyone this account holder has already found, or already contacted.

    Both, deliberately. A username that came back in an earlier search is
    not a new lead, and one already imported as a target has been written
    to — turning either up again wastes the budget on somebody who is
    already on a list.
    """
    known: set[str] = set()
    try:
        rows = (await database.session.execute(
            text(
                "SELECT DISTINCT l.username FROM outreach_leads l "
                "  JOIN outreach_lead_searches s ON s.id = l.search_id "
                " WHERE l.platform = :platform "
                "   AND (s.user_id = :uid OR :uid IS NULL)"
            ),
            {"platform": platform, "uid": user_id},
        )).all()
        known.update(r[0] for r in rows if r[0])

        rows = (await database.session.execute(
            text(
                "SELECT DISTINCT t.username FROM outreach_targets t "
                "  JOIN outreach_campaigns c ON c.id = t.campaign_id "
                " WHERE c.platform = :platform "
                "   AND (c.user_id = :uid OR :uid IS NULL)"
            ),
            {"platform": platform, "uid": user_id},
        )).all()
        known.update(r[0] for r in rows if r[0])
    except Exception:  # noqa: BLE001 — a failed lookup must not stop a search
        traceback.print_exc()
    return known


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

    Several run at once, but never two on one account — they would share
    its session — and never more than the server's limit, because each one
    is a browser of its own. Raises ValueError when either would be broken.
    """
    search_id = int(search["id"])
    limit = int(settings["outreach_discovery_max_concurrent"])
    if running_count() >= limit:
        raise ValueError(f"{limit} searches are already running. Wait for one to finish.")
    if int(account["id"]) in busy_account_ids():
        raise ValueError(
            f"{account.get('name') or 'That account'} is already running a search. "
            f"Wait for it to finish, or use another discovery account.")

    run = Run(search_id=search_id, wanted=int(search.get("wanted") or 0))
    _ACCOUNT_OF[search_id] = int(account["id"])
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
    screen = None
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
            # No 24-hour ceiling on how many profiles an account may open.
            # It was a number we picked, and it stopped searches that the
            # platform was perfectly willing to serve. A platform that has
            # had enough says so, and that is what stands a run down.
            wanted = min(int(search.get("wanted") or 50), per_search)
            run.wanted = wanted

            # --- what to search for ------------------------------------
            run.status = STATUS_RUNNING
            seeds = _seed_list(search.get("seed_accounts"))
            if seeds:
                # Named accounts need no expansion: the operator has already
                # said exactly whose audience they want.
                plan = {"hashtags": [], "terms": [], "seeds": seeds}
                # Followers are read first (below), so this is what happens first.
                run.message = f"Reading the followers of {len(seeds)} account(s)…"
            else:
                run.message = "Working out what to search for…"
                await _persist_status(search_id, STATUS_RUNNING, run.message, 0, 0,
                                      started=True)
                plan = await lead_ai.expand_query(
                    database, search.get("niche") or "", search.get("location") or "",
                    search.get("interests") or "", platform=platform, user_id=user_id,
                )
            known = await already_known(database, user_id, platform)
        finally:
            await database.close()

        if known:
            print(f"[discovery] skipping {len(known)} profile(s) already found "
                  f"or already contacted", flush=True)

        await _persist_status(search_id, STATUS_RUNNING, run.message, 0, 0, started=True)
        await _persist_queries(search_id, plan)
        if not seeds:
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
            # Reads go out through this account's own address too. Four
            # accounts sharing one IP is the most obvious thing about them,
            # and a harvest is the most visible thing they do.
            "proxy_url": decrypt_session(account.get("proxy_url_encrypted")),
        }
        # Headed only where the platform actually needs it — X serves no
        # timeline to a headless browser, and says so by setting
        # HEADED_DISCOVERY. Everywhere else a harvest runs headless, which
        # is what stops a window opening on the operator's screen every time
        # a search runs on a machine with no Xvfb to hide it.
        #
        # A screen of its own when one is needed, because the shared one is
        # what a viewer ticket falls back to when the pool has nothing left.
        # Two reasons to show a window, and the platform's is the one that
        # cannot be overruled: X serves no timeline to a headless browser,
        # so a headless harvest there finds nothing and calls it "no
        # results". The operator's preference decides everywhere else.
        headed = (discovery_needs_headed(driver_name)
                  or not bool(int(settings.get("outreach_headless", 1))))
        screen = await display_pool.acquire() if headed else None
        driver = get_driver(driver_name, headless=not headed,
                            launch_env=screen.env if screen else None)
        await driver.startup()

        collected: list[dict[str, Any]] = []
        #: When progress was last written to the row the dashboard reads.
        last_written = [time.monotonic()]

        async def show_progress(visited_now: int = 0, force: bool = False) -> None:
            """Write what has been found so far, occasionally.

            The row used to be written once at the start with zeros and not
            again until the run ended, so a search that was working looked
            identical to one that was doing nothing — for as long as it ran.
            A harvest of 94 profiles reported `0 found, 0 visited` the whole
            way through and only told the truth when it was cancelled.

            Throttled because this is reporting, not the work: a write per
            profile would be hundreds of round trips to make a number move.
            """
            now = time.monotonic()
            if not force and now - last_written[0] < PROGRESS_EVERY_SECONDS:
                return
            last_written[0] = now
            await _persist_status(
                search_id, STATUS_RUNNING, run.message, len(collected), visited_now
            )

        async def on_found(lead: dict[str, Any]) -> None:
            collected.append(lead)
            run.found = len(collected)
            run.message = f"Found {len(collected)} of {wanted}…"
            # Bank it now, not at the end. The driver was taught to hand
            # people over as it reads them precisely so a long run could
            # survive being stopped — and then every one of them sat in
            # this list until the whole read finished, so a run that was
            # killed at ninety minutes stored nothing at all. A read of
            # this post takes hours; it cannot be all-or-nothing.
            await _store_lead_now(search_id, user_id, platform, lead)
            await show_progress()

        posts = await expand_short_links(post_urls_in(list(seeds)))
        if posts:
            wants_likers = bool(search.get("include_likers"))
            # Commenters unless explicitly switched off: a seed with
            # neither box ticked should still read something rather than
            # opening the post and reporting nobody.
            wants_comments = bool(search.get("include_commenters")) or not wants_likers
            reading = " and ".join(
                [w for w, on in (("comments", wants_comments),
                                 ("likes", wants_likers)) if on]
            ) or "comments"
            run.message = f"Reading the {reading} on {len(posts)} post(s)…"
            leads = await driver.discover_from_posts(
                payload,
                post_urls=tuple(posts),
                limit=wanted,
                interval_seconds=float(settings["outreach_discovery_interval_seconds"]),
                should_stop=lambda: search_id in _CANCELLED,
                on_found=on_found,
                exclude=known,
                include_commenters=wants_comments,
                include_likers=wants_likers,
                # Default on when the row predates the column, which is the
                # behaviour the threads deserve — they hold most of the people.
                include_replies=bool(search.get("include_replies", True)),
            )
        elif seeds:
            # Followers first, then engagement. The follower list is the
            # thing an operator names an account for, and it is short — the
            # platforms show seventy to a hundred names of it however many
            # followers there are — so it is read in a few minutes. It used
            # to come last, after 25 posts' worth of likers, and a run
            # stopped part-way through the posts never read it at all
            # (search 47, 2026-09-27). The posts are where the volume is
            # (measured across four seeds: 108 from follower lists, 776 from
            # posts), so they fill the rest.
            run.message = f"Reading the followers of {len(seeds)} account(s)…"
            leads = await driver.discover_followers(
                payload,
                seeds=tuple(seeds),
                limit=wanted,
                interval_seconds=float(settings["outreach_discovery_interval_seconds"]),
                # Enough rounds for the number asked for, not a fixed
                # depth. A followers list yields roughly a dozen new people
                # per scroll, so a request for a thousand needs about ninety
                # — and stops early anyway once it has them, or once the
                # list genuinely ends.
                scroll_rounds=max(
                    int(settings["outreach_discovery_scroll_rounds"]) * 3,
                    wanted // 10 + 20,
                ),
                should_stop=lambda: search_id in _CANCELLED,
                on_found=on_found,
                exclude=known,
            )
            if (len(leads) < wanted and search_id not in _CANCELLED
                    and hasattr(driver, "discover_from_engagement")):
                run.message = f"Reading who engages with recent posts by {len(seeds)} account(s)…"
                already = {lead["username"].lower() for lead in leads}
                leads = leads + await driver.discover_from_engagement(
                    payload,
                    seeds=tuple(seeds),
                    limit=wanted - len(leads),
                    interval_seconds=float(
                        settings["outreach_discovery_interval_seconds"]),
                    should_stop=lambda: search_id in _CANCELLED,
                    on_found=on_found,
                    # Everyone the follower pass returned, as well as everyone
                    # known before — otherwise the posts offer the same people
                    # again and the count stalls without saying why.
                    exclude=known | already,
                )
        else:
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
                exclude=known,
            )
        visited = len(leads)

        # --- optional: open each profile for a bio ---------------------
        if search.get("enrich_profiles") and leads:
            run.message = f"Reading {len(leads)} profile(s)…"
            await show_progress(visited, force=True)
            context = await driver._context_for(payload)
            page = await context.new_page()
            try:
                for index, lead in enumerate(leads, start=1):
                    if search_id in _CANCELLED:
                        break
                    lead.update(await driver.profile_summary(page, lead["username"]))
                    visited += 1
                    run.message = f"Read {index} of {len(leads)} profile(s)…"
                    await show_progress(visited)
                    await asyncio.sleep(
                        float(settings["outreach_discovery_interval_seconds"])
                    )
            finally:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass

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

        # A run that stops well short of what was asked, quickly, has not
        # found everything there was — the platform stopped feeding it.
        # Instagram throttles sustained harvesting, and back-to-back runs
        # on one account show it plainly: 988 profiles, then 48. Saying
        # "found 48" without saying why invites running it again straight
        # away, which is the one thing that makes it worse.
        elapsed = (datetime.now(timezone.utc) - _started(run)).total_seconds()
        throttled = stored < wanted * 0.6 and elapsed < 120

        if not stored:
            message = "No profiles found. Try a broader niche, or different wording."
        elif throttled:
            message = (
                f"Found {stored} of {wanted} and then the platform stopped "
                f"returning more — that is throttling, not the end of the list. "
                f"Leave it an hour before running this account again; going "
                f"straight back makes it worse."
            )
        else:
            message = f"Found {stored} profile(s). Review them and import the ones you want."
        finish(STATUS_DONE, message)
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
        # After the browser, not before: releasing the screen kills the X
        # server the browser is still drawing on.
        await display_pool.release(screen)


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


async def _store_lead_now(search_id: int, user_id: Optional[int],
                          platform: str, lead: dict[str, Any]) -> None:
    """Write one lead the moment it is found, on its own connection.

    Storing is reporting, not the work: a row that will not save must
    not take the run down with it, and the final `_store_leads` sweep
    is idempotent, so anything missed here is still written at the end.
    """
    database = await db.get_db()
    try:
        await _store_leads(database, search_id, user_id, platform, [lead])
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    finally:
        await database.close()


async def _store_leads(database, search_id: int, user_id: Optional[int],
                       platform: str, leads: list[dict[str, Any]]) -> int:
    """Write what was found, filling in anything learned since.

    A lead is written twice now: once the moment the reader finds it, so
    a run that is stopped keeps its work, and once at the end with
    whatever the profile read and the scorer added. The second write has
    to be an update, not a no-op — `DO NOTHING` would keep the bare row
    banked during the read and silently throw away the bio, the follower
    count, the score and the reason.

    It fills rather than replaces: a column already holding something
    keeps it unless the new row actually has a value for it, so the
    end-of-run sweep can never blank what the live write banked.
    """
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
                    "ON CONFLICT (search_id, username) DO UPDATE SET "
                    "  display_name = COALESCE(EXCLUDED.display_name, "
                    "                          outreach_leads.display_name), "
                    "  bio          = COALESCE(EXCLUDED.bio, "
                    "                          outreach_leads.bio), "
                    "  followers    = COALESCE(EXCLUDED.followers, "
                    "                          outreach_leads.followers), "
                    "  source       = COALESCE(EXCLUDED.source, "
                    "                          outreach_leads.source), "
                    "  score        = COALESCE(EXCLUDED.score, "
                    "                          outreach_leads.score), "
                    "  reason       = COALESCE(EXCLUDED.reason, "
                    "                          outreach_leads.reason)"
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
