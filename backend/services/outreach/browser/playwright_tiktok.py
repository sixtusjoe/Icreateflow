"""Playwright driver for the TikTok web messaging interface.

One browser process, one `BrowserContext` per sending account. The context
is the isolation boundary: separate cookie jar, separate local storage,
separate cache. Two accounts can never see each other's authentication
state, and a context is only torn down when the account is released — the
session survives between jobs.

Authentication is imported, never performed here. The operator signs in
themselves and hands the pipeline the resulting Playwright storage-state
JSON; this module loads it and nothing else. There is no password field in
this file by design (see SECURITY in the outreach README section).

Page structure is the one thing here guaranteed to rot. Every selector
lives in `SELECTORS` at the top with several fallbacks, and any miss comes
back as `unexpected_page` rather than an exception, so a TikTok redesign
degrades into a clearly-labelled failure the operator can see on the
dashboard instead of a crashed worker.

Requires the optional extras::

    pip install playwright && playwright install chromium
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.outreach.browser import MessageResult
from services.outreach.constants import (
    RESULT_ABORTED,
    RESULT_BROWSER_ERROR,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SESSION_EXPIRED,
    RESULT_UNEXPECTED_PAGE,
)

#: Ordered fallbacks — the first selector that resolves wins.
SELECTORS: dict[str, tuple[str, ...]] = {
    # Something proving the profile actually rendered, so the button checks
    # don't run against a shell that has not hydrated yet.
    "profile_loaded": (
        "[data-e2e='user-title']",
        "[data-e2e='user-subtitle']",
        "[data-e2e='followers-count']",
        "h1",
    ),
    "profile_missing": (
        "text=Couldn't find this account",
        "text=Couldn't find this account.",
        "text=This account is private",
    ),
    "login_wall": (
        "[data-e2e='login-button']",
        "text=Log in to TikTok",
        "text=Sign up for TikTok",
    ),
    # Tiered, most specific first. Ordering matters: "anything containing the
    # word Message" would happily match a nav item, and _first_visible races
    # its selectors, so the loosest could win. Tiers are tried in sequence;
    # only the selectors inside one tier race each other.
    "message_button": (
        ("[data-e2e='message-button']", "[data-e2e='message-button-inline']"),
        # TikTok builds most of its controls out of divs, not <button>.
        #
        # `:text-is` (exact) rather than `:has-text` (substring) is load
        # bearing: TikTok's left navigation has a "Messages" entry, which
        # contains the word "Message", and because _first_visible races its
        # selectors that nav link can win over the profile's own control.
        # Clicking it navigates to the inbox — which is exactly the
        # "composer never opened, page offers inbox-title|…" failure seen in
        # production.
        (
            "button:text-is('Message')",
            "a:text-is('Message')",
            "div[role='button']:text-is('Message')",
            "[role='button']:text-is('Message')",
        ),
    ),
    "message_input": (
        "[data-e2e='message-input-area']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
    ),
    # The DM inbox: a list of conversations with none of them open. Landing
    # here after clicking Message means no thread was started, so there is
    # nothing to type into.
    "messages_view": (
        "[data-e2e='chat-list']",
        "[data-e2e='inbox-title']",
        "[data-e2e='chat-list-item']",
    ),
    "send_button": (
        "[data-e2e='message-send']",
        "button[type='submit']:has-text('Send')",
        "svg[data-e2e='message-send-icon']",
    ),
    "sent_confirmation": (
        "[data-e2e='chat-item']",
        "div[class*='DivChatItem']",
    ),
    "rate_limited": (
        "text=You're sending messages too fast",
        "text=Too many attempts",
    ),
    # TikTok's human-verification puzzle. It renders *over* a perfectly
    # normal profile: the Message button is right there and visible, so
    # every check above passes and the click simply never lands. Without
    # this the driver reports "no Message button" and the queue skips a
    # good target for good.
    #
    # Matched by container id/class as well as text, because the wording is
    # localised and the puzzle has several variants (slider, rotate, pick
    # two objects).
    "verification_challenge": (
        "#captcha-verify-container",
        "#captcha_container",
        "div[id*='captcha-verify']",
        "div[class*='captcha_verify_container']",
        "text=Drag the slider to fit the puzzle",
        "text=Verify to continue",
        "text=Slide to verify",
        "text=Verification failed",
    ),
}

#: A frame whose URL looks like the captcha service. The puzzle is often
#: served in an iframe, and `page.locator` does not search into frames — so
#: a selector-only check sees a blank page and calls it healthy.
CHALLENGE_FRAME_HINTS = ("captcha", "verify", "secsdk")

#: How long to hold the browser open on a verification puzzle so a person
#: can solve it.
#:
#: A headless worker waits zero — nobody is there, and failing fast is what
#: keeps the account from being ground down. But `outreach-watch.sh` runs
#: with a visible browser over VNC precisely so somebody CAN clear it, and
#: bailing out instantly closes the window in their face. So the default is
#: the operator's patience, not the worker's.
CHALLENGE_WAIT_MS = int(os.environ.get("ICREATE_OUTREACH_CHALLENGE_WAIT_MS", "0"))
CHALLENGE_WAIT_HEADFUL_MS = int(
    os.environ.get("ICREATE_OUTREACH_CHALLENGE_WAIT_HEADFUL_MS", "300000")
)

DEFAULT_TIMEOUT_MS = int(os.environ.get("ICREATE_OUTREACH_TIMEOUT_MS", "30000"))
#: How long to let the profile shell hydrate before looking for anything.
PROFILE_READY_MS = int(os.environ.get("ICREATE_OUTREACH_PROFILE_READY_MS", "12000"))
#: Budget for finding the Message button. The old 2.5s was tuned against a
#: local stub that rendered instantly; a real profile on a cold server is
#: nowhere near that fast, and running out of time here is indistinguishable
#: from the button being absent.
MESSAGE_BUTTON_MS = int(os.environ.get("ICREATE_OUTREACH_MESSAGE_BUTTON_MS", "15000"))
#: Per-click budget. The context default (30s) is far too long to spend
#: discovering that something is covering the button.
CLICK_MS = int(os.environ.get("ICREATE_OUTREACH_CLICK_MS", "10000"))
#: Budget for the composer to appear after clicking Message. Clicking it can
#: navigate to a whole separate messages app rather than opening an inline
#: box, and 8s was another stub-speed number that a real page misses.
COMPOSER_MS = int(os.environ.get("ICREATE_OUTREACH_COMPOSER_MS", "15000"))

#: Rows in the inbox conversation list, matched by their own text.
THREAD_ROWS = "[data-e2e='chat-list-item'], [data-e2e='inbox-title']"

#: Things that sit on top of the profile and swallow clicks. A consent
#: banner intercepting pointer events is indistinguishable from a dead
#: button: Playwright waits for the element to receive events, and times out.
OVERLAY_DISMISS = (
    "tiktok-cookie-banner >>> button:has-text('Decline all')",
    "tiktok-cookie-banner >>> button:has-text('Allow all')",
    "button:has-text('Decline all')",
    "button:has-text('Decline optional cookies')",
    "button:has-text('Allow all')",
    "[data-e2e='modal-close-inner-button']",
    "div[role='button']:has-text('Not now')",
    "button:has-text('Not now')",
)
#: Where to drop a screenshot when a send cannot be verified. Set to "" to
#: turn it off. These are the fastest way to tell a changed selector from a
#: blocked account without watching a live browser.
DEBUG_DIR = os.environ.get("ICREATE_OUTREACH_DEBUG_DIR", "outreach-debug")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class PlaywrightTikTokMessenger:
    """Drives tiktok.com's DM UI with one isolated context per account."""

    name = "playwright_tiktok"

    def __init__(
        self,
        headless: Optional[bool] = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        user_agent: str = DEFAULT_USER_AGENT,
        **_ignored: Any,
    ):
        if headless is None:
            headless = os.environ.get("ICREATE_OUTREACH_HEADLESS", "1") not in ("0", "false")
        self._headless = headless
        self._timeout = timeout_ms
        self._user_agent = user_agent
        self._playwright = None
        self._browser = None
        #: account_id → BrowserContext. The isolation guarantee.
        self._contexts: dict[int, Any] = {}
        self._lock = asyncio.Lock()

    # --- lifecycle -------------------------------------------------------

    async def startup(self) -> None:
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright  # imported lazily

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

    async def shutdown(self) -> None:
        for account_id in list(self._contexts):
            await self.release_account(account_id)
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def release_account(self, account_id: int) -> None:
        """Close this account's context without discarding its session."""
        context = self._contexts.pop(int(account_id), None)
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001 — teardown must not raise
                pass

    async def _context_for(self, account: dict[str, Any]):
        """Get (or build) the isolated context for one account."""
        account_id = int(account["id"])
        async with self._lock:
            context = self._contexts.get(account_id)
            if context is not None:
                return context

            await self.startup()
            options: dict[str, Any] = {
                "user_agent": self._user_agent,
                "viewport": {"width": 1280, "height": 900},
                "locale": "en-US",
            }
            if account.get("proxy_url"):
                options["proxy"] = {"server": account["proxy_url"]}
            state = account.get("session_state")
            if state:
                options["storage_state"] = (
                    json.loads(state) if isinstance(state, str) else state
                )
            context = await self._browser.new_context(**options)
            context.set_default_timeout(self._timeout)
            self._contexts[account_id] = context
            return context

    # --- helpers ---------------------------------------------------------

    @staticmethod
    async def _first_visible(page, keys: tuple[str, ...], timeout_ms: int = 2500):
        """Whichever of these selectors becomes visible first, or None.

        Races them concurrently rather than trying each in turn. Waiting in
        series costs `timeout × len(keys)` whenever the page has changed and
        none of them will ever match — with the composer's 8s budget and three
        fallbacks that is 24 seconds burned per job before giving up. Racing
        gives every selector the full budget and still bounds the total at one.
        """
        async def wait_for(selector):
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return locator

        pending = {asyncio.create_task(wait_for(s)) for s in keys}
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    # A miss raises; only a hit returns a locator.
                    if not task.cancelled() and task.exception() is None:
                        return task.result()
            return None
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    @staticmethod
    async def _present(page, keys: tuple[str, ...]) -> bool:
        """Is any of these selectors visible *right now*?

        Deliberately does not wait. Every caller is asking "did the page come
        back in a bad state?" after navigation already settled, and there are
        eight such selectors across the checks — waiting out a per-selector
        timeout would add ~10s of dead time to every successful send.
        """
        for selector in keys:
            try:
                if await page.locator(selector).first.is_visible(timeout=250):
                    return True
            except Exception:  # noqa: BLE001 — a miss is expected, try the next
                continue
        return False

    @staticmethod
    async def _composer_cleared(editor, attempts: int = 20) -> bool:
        """Did the input box empty out after the send?

        The app clearing the composer is the one signal that it accepted the
        submission. Polls rather than waiting a fixed beat, because the clear
        happens on the network round-trip. A composer that has been detached
        entirely also counts — the view moved on.
        """
        for _ in range(attempts):
            try:
                remaining = (await editor.inner_text(timeout=1000)) or ""
            except Exception:  # noqa: BLE001 — element gone: the view moved on
                return True
            if not remaining.strip():
                return True
            await asyncio.sleep(0.25)
        return False

    async def _first_visible_tiered(self, page, tiers, timeout_ms: int = 2500):
        """Try groups of selectors in order, racing within each group.

        Specificity has to beat latency here. A generic
        `[role="button"]:has-text("Message")` will match a nav entry as
        happily as the real control, and because `_first_visible` races its
        selectors, the loosest one can win the race and get clicked. Tiers
        keep the precise `data-e2e` hooks strictly ahead of the guesses,
        while still racing the alternatives inside each tier.

        A flat tuple of strings is treated as a single tier, so the other
        selector groups keep working unchanged.
        """
        if tiers and isinstance(tiers[0], str):
            tiers = (tiers,)
        for tier in tiers:
            found = await self._first_visible(page, tuple(tier), timeout_ms)
            if found is not None:
                return found
        return None

    async def _dismiss_overlays(self, page) -> list[str]:
        """Click away consent banners and modals covering the page.

        Best-effort and quiet: every selector here is optional, and a miss
        is the normal case once the banner has been accepted for a session.
        """
        dismissed = []
        for selector in OVERLAY_DISMISS:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=400):
                    await locator.click(timeout=2000)
                    dismissed.append(selector)
                    await page.wait_for_timeout(300)
            except Exception:  # noqa: BLE001 — none of these are required
                continue
        return dismissed

    async def _click(self, page, locator, what: str, username: str) -> bool:
        """Click something, working around whatever is sitting on top of it.

        A plain `.click()` waits for Playwright's actionability checks —
        visible, stable, receives events — and a consent banner overlaying
        the button fails the last one until the timeout expires. So: try
        normally, clear overlays and retry, then fall back to bypassing the
        checks entirely rather than losing the job to a cookie notice.
        """
        try:
            await locator.click(timeout=CLICK_MS)
            return True
        except Exception:  # noqa: BLE001 — fall through to the recovery path
            pass

        dismissed = await self._dismiss_overlays(page)
        if dismissed:
            print(f"[outreach] dismissed overlay(s) before {what}: {dismissed}", flush=True)
            try:
                await locator.click(timeout=CLICK_MS)
                return True
            except Exception:  # noqa: BLE001
                pass

        for how in ("force", "js"):
            try:
                if how == "force":
                    await locator.click(timeout=CLICK_MS, force=True)
                else:
                    await locator.evaluate("el => el.click()")
                print(f"[outreach] {what}: needed a {how} click", flush=True)
                return True
            except Exception:  # noqa: BLE001
                continue

        await self._save_debug_shot(page, username, f"click-failed-{what}")
        print(
            f"[outreach] {what}: click failed on {page.url} — "
            f"page offers: {await self._page_actions(page)}",
            flush=True,
        )
        return False

    async def _open_thread(self, page, target: dict[str, Any]) -> bool:
        """Open this target's conversation from the inbox list.

        Clicking Message does not always open a composer in place: TikTok
        can hand off to its messages app, and if the thread does not get
        selected you are left looking at a list of every conversation the
        account has.

        Only ever opens a row whose label matches this target exactly. A
        fuzzy match is not acceptable here — the rows are other people's
        conversations, and clicking the nearest-looking one sends a stranger
        a DM meant for someone else. Failing the job is the cheaper mistake,
        so anything short of an exact match returns False.
        """
        wanted = {
            str(value).strip().lstrip("@").lower()
            for value in (
                target.get("username"),
                target.get("display_name"),
                target.get("nickname"),
            )
            if value
        }
        if not wanted:
            return False

        rows = page.locator(THREAD_ROWS)
        try:
            count = await rows.count()
        except Exception:  # noqa: BLE001 — no list, nothing to open
            return False

        for index in range(min(count, 40)):
            row = rows.nth(index)
            try:
                label = ((await row.inner_text(timeout=500)) or "").strip()
            except Exception:  # noqa: BLE001 — row went away mid-scan
                continue
            if label.lstrip("@").lower() not in wanted:
                continue
            username = str(target.get("username") or "target")
            if await self._click(page, row, "chat-list-item", username):
                print(f"[outreach] opened the existing thread for {label}", flush=True)
                return True
            return False
        return False

    @staticmethod
    async def _page_actions(page, limit: int = 30) -> list[str]:
        """Every clickable thing on the page, as `data-e2e|label`.

        When a selector misses, the useful question isn't "which selector
        failed" — it's "what is on the page instead". This turns a stale
        attribute into a one-line diff in the worker log, without anyone
        having to open a browser against the live site.
        """
        try:
            return await page.evaluate(
                """(limit) => Array.from(
                        document.querySelectorAll('button, a[role="button"], a')
                    )
                    .map(el => {
                        const e2e = el.getAttribute('data-e2e') || '';
                        const text = (el.innerText || '').trim().slice(0, 40);
                        return (e2e || text) ? `${e2e}|${text}` : null;
                    })
                    .filter(Boolean)
                    .slice(0, limit)""",
                limit,
            )
        except Exception as exc:  # noqa: BLE001 — diagnostics must never raise
            # Never return a bare [] here. An empty list already means "the
            # page offered nothing clickable", and a production failure was
            # misread for exactly that reason: `page offers: []` was taken as
            # evidence about the page when in fact this call had thrown and
            # the page was never inspected at all. Say which happened.
            return [f"<page-actions failed: {type(exc).__name__}: {exc}>"]

    @staticmethod
    async def _page_frames(page) -> list[str]:
        """The URLs of every frame on the page, main frame excluded.

        Pairs with `_page_actions`: that only ever sees the top document, so
        a page whose real content is in an iframe — the verification puzzle,
        for one — reads as empty. When the action list looks bare, this says
        whether there was somewhere else to look.
        """
        try:
            return [f.url for f in page.frames if f is not page.main_frame][:10]
        except Exception as exc:  # noqa: BLE001
            return [f"<frames failed: {type(exc).__name__}: {exc}>"]

    async def _challenge_present(self, page) -> bool:
        """Is TikTok showing a human-verification puzzle?

        Checked on the page itself and across its frames. The puzzle is
        commonly served in an iframe, and `page.locator` does not descend
        into frames, so selectors alone miss it and the profile underneath
        looks perfectly healthy.

        Deliberately only ever *detects*. Solving the puzzle is a person's
        job — `outreach-watch.sh` puts the browser on screen for exactly
        that.
        """
        if await self._present(page, SELECTORS["verification_challenge"]):
            return True
        try:
            for frame in page.frames:
                if frame is page.main_frame:
                    continue
                url = (frame.url or "").lower()
                if any(hint in url for hint in CHALLENGE_FRAME_HINTS):
                    return True
        except Exception:  # noqa: BLE001 — a frame can vanish mid-check
            pass
        return False

    @staticmethod
    def _page_is_gone(page) -> bool:
        """Did the page disappear underneath us?

        Every selector helper swallows its own exceptions, so a page closed
        mid-job does not raise — it just makes every lookup return None,
        which reads exactly like "this profile has no Message button". That
        cost a live target: the watch script stops the background workers,
        systemd killed a mid-send worker together with its Chromium, and the
        job recorded messaging_unavailable, which is terminal.
        """
        try:
            return page.is_closed()
        except Exception:  # noqa: BLE001 — no page left to ask
            return True

    def _challenge_wait_ms(self) -> int:
        """How long to let a human clear a puzzle. 0 = don't wait."""
        if CHALLENGE_WAIT_MS:
            return CHALLENGE_WAIT_MS  # explicit override wins either way
        return 0 if self._headless else CHALLENGE_WAIT_HEADFUL_MS

    async def _challenge_cleared_by_hand(self, page, username: str) -> bool:
        """Hold on a verification puzzle while somebody solves it.

        Returns True if it went away in time, False if it is still there —
        in which case the caller reports `challenge_required` exactly as
        before. The driver never touches the puzzle itself.
        """
        budget_ms = self._challenge_wait_ms()
        if budget_ms <= 0:
            return False

        print(
            f"[outreach] verification puzzle on @{username} — waiting up to "
            f"{budget_ms // 1000}s for someone to solve it in the browser window",
            flush=True,
        )
        deadline = time.monotonic() + (budget_ms / 1000)
        while time.monotonic() < deadline:
            await page.wait_for_timeout(1000)
            if not await self._challenge_present(page):
                print("[outreach] puzzle cleared — carrying on", flush=True)
                return True
        print(
            f"[outreach] puzzle still up after {budget_ms // 1000}s — giving up",
            flush=True,
        )
        return False

    async def _save_debug_shot(self, page, username: str, reason: str) -> Optional[str]:
        """Screenshot a page that did not verify, for selector diagnosis.

        Only ever written on a failure, so a healthy campaign leaves nothing
        behind. Best-effort: a screenshot that fails must not turn a
        reportable failure into an exception.
        """
        if not DEBUG_DIR:
            return None
        try:
            directory = Path(DEBUG_DIR)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            path = directory / f"{stamp}-{username or 'target'}-{reason}.png"
            await page.screenshot(path=str(path), full_page=False)
            print(f"[outreach] saved debug screenshot: {path}", flush=True)
            return str(path)
        except Exception as exc:  # noqa: BLE001
            # Say so. A silent None here is indistinguishable from "debug
            # shots are switched off", and the failure that most needs a
            # screenshot is exactly the one where taking it goes wrong.
            print(
                f"[outreach] could not save debug screenshot ({reason}): "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return None

    # --- the one method the pipeline calls -------------------------------

    async def send_message(
        self, account: dict[str, Any], target: dict[str, Any], message: str
    ) -> MessageResult:
        """Load the profile, open DMs, type, send, verify.

        Returns a structured result for every expected outcome; the caller
        decides whether that means retry, skip, or pause the account.
        """
        if not account.get("session_state"):
            return MessageResult.failure(
                RESULT_SESSION_EXPIRED,
                "No stored browser session for this account — import one before sending.",
            )

        page = None
        url = target.get("profile_url") or ""
        target_username = str(target.get("username") or "target")
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeout

            context = await self._context_for(account)
            page = await context.new_page()

            # 1-2. Navigate to the target profile.
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            except PlaywrightTimeout:
                return MessageResult.failure(
                    RESULT_NAVIGATION_TIMEOUT,
                    f"Timed out loading {url}",
                    url=url,
                )

            # TikTok's profile is a client-rendered shell: domcontentloaded
            # fires long before the action buttons exist. Give it a beat to
            # paint something recognisable, or every check below races an
            # empty page and reports "no Message button" on profiles that
            # plainly have one.
            await self._first_visible(
                page, SELECTORS["profile_loaded"], timeout_ms=PROFILE_READY_MS
            )

            if await self._present(page, SELECTORS["profile_missing"]):
                return MessageResult.failure(
                    RESULT_PROFILE_UNAVAILABLE,
                    "Profile not found or private",
                    url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "profile-missing"),
                )
            if await self._present(page, SELECTORS["login_wall"]):
                # The stored session no longer authenticates us.
                return MessageResult.failure(
                    RESULT_SESSION_EXPIRED,
                    "Session expired — TikTok is showing the login wall",
                    url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "login-wall"),
                )
            if await self._present(page, SELECTORS["rate_limited"]):
                return MessageResult.failure(
                    RESULT_RATE_LIMITED, "Platform is rate limiting this account", url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "rate-limited"),
                )
            # Before anything is concluded about the target: is there a
            # verification puzzle over this page? It sits on top of a
            # completely normal profile, so every check below misreads it —
            # the button is found but unclickable, or not found at all, and
            # the target gets skipped as "doesn't accept DMs".
            if await self._challenge_present(page) and not await (
                self._challenge_cleared_by_hand(page, target_username)
            ):
                return MessageResult.failure(
                    RESULT_CHALLENGE_REQUIRED,
                    "TikTok is asking this account to pass a verification puzzle. "
                    "Nothing is wrong with the target — a person has to solve it "
                    "(deploy/outreach-watch-mac.sh shows the browser), then resume "
                    "the account",
                    url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "challenge"),
                )

            # 3-4. Is the messaging interface available, and open it.
            message_button = await self._first_visible_tiered(
                page, SELECTORS["message_button"], timeout_ms=MESSAGE_BUTTON_MS
            )
            if message_button is None and self._page_is_gone(page):
                return MessageResult.failure(
                    RESULT_ABORTED,
                    "The browser closed before the Message button could be found "
                    "— most likely the worker was stopped mid-job. Nothing was "
                    "learned about this target",
                    url=url,
                )
            if message_button is None:
                # Two very different causes, indistinguishable from here: the
                # target may not accept DMs from this account, or the button's
                # markup may have moved. Capture what the page actually offers
                # so the log answers that rather than the message guessing.
                actions = await self._page_actions(page)
                shot = await self._save_debug_shot(page, target_username, "no-message-button")
                print(
                    f"[outreach] no Message button on {url} — page offers: {actions} "
                    f"— frames: {await self._page_frames(page)}",
                    flush=True,
                )
                return MessageResult.failure(
                    RESULT_MESSAGING_UNAVAILABLE,
                    "No Message button on this profile — either it doesn't accept "
                    "DMs from this account, or the button has moved",
                    url=url, screenshot=shot, page_actions=actions,
                )
            if not await self._click(page, message_button, "message-button", target_username):
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    "Found the Message button but could not click it — something "
                    "is covering it, or it never became interactive",
                    url=page.url,
                )

            editor = await self._first_visible(
                page, SELECTORS["message_input"], timeout_ms=COMPOSER_MS
            )

            # Clicking Message can hand off to the messages app instead of
            # opening a box in place. When the thread does not come with it
            # we land on the inbox — a list of every conversation and no
            # composer at all — so pick the target's own thread out of it.
            if editor is None and await self._present(page, SELECTORS["messages_view"]):
                if await self._open_thread(page, target):
                    editor = await self._first_visible(
                        page, SELECTORS["message_input"], timeout_ms=COMPOSER_MS
                    )

            if editor is None and self._page_is_gone(page):
                return MessageResult.failure(
                    RESULT_ABORTED,
                    "The browser closed before the composer could open — most "
                    "likely the worker was stopped mid-job",
                    url=url,
                )
            if editor is None:
                if await self._present(page, SELECTORS["login_wall"]):
                    return MessageResult.failure(
                        RESULT_SESSION_EXPIRED, "Session expired at the message step", url=url
                    )
                if await self._challenge_present(page) and not await (
                    self._challenge_cleared_by_hand(page, target_username)
                ):
                    return MessageResult.failure(
                        RESULT_CHALLENGE_REQUIRED,
                        "A verification puzzle appeared after clicking Message. "
                        "The target is fine — a person has to solve it, then "
                        "resume the account",
                        url=page.url,
                        screenshot=await self._save_debug_shot(
                            page, target_username, "challenge"
                        ),
                    )
                on_inbox = await self._present(page, SELECTORS["messages_view"])
                actions = await self._page_actions(page)
                print(
                    f"[outreach] composer never opened on {page.url} "
                    f"({'inbox, no thread open' if on_inbox else 'not the inbox'}) — "
                    f"page offers: {actions} — frames: {await self._page_frames(page)}",
                    flush=True,
                )
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    (
                        f"Ended up on the TikTok inbox with no conversation open for "
                        f"@{target_username} — the Message button did not start a thread"
                        if on_inbox
                        else "Message composer did not open — the page structure "
                        "may have changed"
                    ),
                    url=page.url,
                    screenshot=await self._save_debug_shot(page, target_username, "composer-not-open"),
                    page_actions=actions,
                )

            # 5. Enter the message. `type` rather than `fill` — the composer
            # is a contenteditable that ignores programmatic value sets.
            await editor.click()
            await editor.type(message, delay=25)

            # 6. Submit.
            send_button = await self._first_visible(page, SELECTORS["send_button"], timeout_ms=4000)
            if send_button is None or not await self._click(
                page, send_button, "send-button", target_username
            ):
                # Enter submits in most chat composers; the verification
                # below is what decides whether it actually worked.
                await page.keyboard.press("Enter")

            # 7. Verify.
            #
            # The test is: the composer is now EMPTY, and the message text is
            # still somewhere on the page. Together those mean the text moved
            # out of the input and into the conversation.
            #
            # Checking only "is the message text on the page" — which is what
            # this did originally — is worthless: the composer is part of the
            # page, so a send that silently did nothing left the text sitting
            # in the box and the check happily called it delivered. That is a
            # campaign reporting thousands sent having sent none, so it is
            # worth being strict here.
            #
            # Deliberately not matched against the thread's own markup: class
            # names are the first thing a redesign changes, and a false
            # negative here costs a duplicate DM on retry.
            await page.wait_for_timeout(1500)
            if await self._present(page, SELECTORS["rate_limited"]):
                return MessageResult.failure(
                    RESULT_RATE_LIMITED, "Rate limited while sending", url=page.url
                )

            composer_cleared = await self._composer_cleared(editor)
            if not composer_cleared:
                await self._save_debug_shot(page, target_username, "composer-not-cleared")
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    "The message is still sitting in the composer — the send "
                    "did not go through",
                    url=page.url,
                )

            try:
                body = (await page.locator("body").inner_text(timeout=3000)) or ""
            except Exception:  # noqa: BLE001
                body = ""
            if message[:60] not in body:
                await self._save_debug_shot(page, target_username, "not-in-thread")
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    "The composer emptied but the message is not visible in the "
                    "conversation — could not confirm delivery",
                    url=page.url,
                )

            return MessageResult.sent(url=page.url)

        except Exception as exc:  # noqa: BLE001 — every browser fault is a result
            name = type(exc).__name__
            detail = str(exc)
            if "Timeout" in name and "click" in detail.lower():
                # A click that timed out is an unclickable element, not a page
                # that failed to load — reporting it as navigation_timeout sent
                # people looking at the wrong thing.
                status = RESULT_UNEXPECTED_PAGE
            elif "Timeout" in name:
                status = RESULT_NAVIGATION_TIMEOUT
            else:
                status = RESULT_BROWSER_ERROR
            return MessageResult.failure(status, f"{name}: {exc}"[:500], url=url)
        finally:
            # 9. Clean up the page — never the context, which holds the session.
            if page is not None:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass

    # --- session capture -------------------------------------------------

    async def export_session(self, account: dict[str, Any]) -> Optional[str]:
        """Dump the account context's current storage state as JSON.

        Called after a successful send so a refreshed cookie set can be
        re-encrypted and stored, keeping long-running accounts signed in.
        """
        context = self._contexts.get(int(account["id"]))
        if context is None:
            return None
        try:
            return json.dumps(await context.storage_state())
        except Exception:  # noqa: BLE001
            return None
