"""The shared Playwright engine behind every platform driver.

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
lives in each platform's `SELECTORS` table with several fallbacks, and any miss comes
back as `unexpected_page` rather than an exception, so a redesign
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
from urllib.parse import quote_plus
from typing import Any, Optional

from services.outreach.browser import MessageResult
from services.outreach.constants import (
    RESULT_ABORTED,
    RESULT_BROWSER_ERROR,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_FOLLOW_PENDING,
    RESULT_MESSAGE_REFUSED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SESSION_EXPIRED,
    RESULT_UNEXPECTED_PAGE,
)

#: Ordered fallbacks — the first selector that resolves wins.

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
#: How long to leave a submitted message alone before confirming it a
#: second time. An optimistic render survives the first look and not the
#: second, which is the difference between a delivery and a lie.
SETTLE_MS = int(os.environ.get("ICREATE_OUTREACH_SETTLE_MS", "2500"))
#: How long to let a lazily-loaded list fetch its next page after a scroll.
SCROLL_PAUSE_MS = int(os.environ.get("ICREATE_OUTREACH_SCROLL_PAUSE_MS", "1200"))
#: How long to wait for a scroll to bring in the next page before calling
#: the list finished, and how often to look while waiting.
LOAD_WAIT_MS = int(os.environ.get("ICREATE_OUTREACH_LOAD_WAIT_MS", "2500"))
SCROLL_POLL_MS = int(os.environ.get("ICREATE_OUTREACH_SCROLL_POLL_MS", "400"))
#: Quiet rounds before a list is called finished, and the longest any one
#: list may be worked. The rounds have a growing pause between them, so
#: this is roughly half a minute of patience before giving up.
DIALOG_QUIET_ROUNDS = int(os.environ.get("ICREATE_OUTREACH_QUIET_ROUNDS", "6"))
DIALOG_BUDGET_MS = int(os.environ.get("ICREATE_OUTREACH_DIALOG_BUDGET_MS", "900000"))
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
MESSAGE_BUTTON_MS = int(os.environ.get("ICREATE_OUTREACH_MESSAGE_BUTTON_MS", "8000"))
#: How long a reloaded page gets to render an existing conversation before
#: the check moves on to reopening it. Not a budget for the send — the send
#: has already happened — just for the thread to draw.
CONFIRM_RENDER_MS = int(os.environ.get("ICREATE_OUTREACH_CONFIRM_RENDER_MS", "4000"))
#: How long to wait for a Message button to appear after following. The
#: profile re-renders in place rather than navigating, so this is a render,
#: not a page load — but it is a render behind a network round trip.
FOLLOW_UNLOCK_MS = int(os.environ.get("ICREATE_OUTREACH_FOLLOW_UNLOCK_MS", "5000"))
#: What a fallback tier gets once the first has already waited out the page.
#: Not a page-load budget — a settled-DOM query, which is instant or never.
LATER_TIER_MS = int(os.environ.get("ICREATE_OUTREACH_LATER_TIER_MS", "1500"))
#: One turn of the composer-versus-blocked race. Short, because its only
#: job is to hand control back so the blocking notices can be looked at.
COMPOSER_POLL_MS = int(os.environ.get("ICREATE_OUTREACH_COMPOSER_POLL_MS", "500"))
#: Per-click budget, and per-typing budget. The context default (30s) is
#: far too long to spend discovering that something is covering the button
#: — or that the composer went stale between being found and being typed
#: into, which showed up in production as three separate half-minute
#: stalls on one run.
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


#: Flags every Chromium this app launches is given.
#:
#: `--disable-features=WebBluetooth` is not a preference, it is a crash fix.
#: macOS aborts any process that touches CoreBluetooth without an
#: `NSBluetoothAlwaysUsageDescription` in its Info.plist, and Playwright's
#: bundled Chromium has none. A page that so much as asks whether Bluetooth
#: is available gets the whole browser killed by TCC:
#:
#:     Termination Reason: Namespace TCC
#:     This app has crashed because it attempted to access privacy-sensitive
#:     data without a usage description.
#:     +[CBManager authorization]
#:
#: It killed a sign-in window nine seconds after it opened, repeatedly,
#: while someone was typing a password into it — and the app reported it as
#: "the window was closed before sign-in finished", because from this side
#: a browser killed by the OS and one closed by hand look identical.
#:
#: The flag removes `navigator.bluetooth` outright, so no page can reach
#: CoreBluetooth at all. Nothing here wants Bluetooth.
CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-features=WebBluetooth",
]


class DiscoveryUnsupported(RuntimeError):
    """This driver cannot find profiles — only message them."""


class PlaywrightMessenger:
    """The engine: one isolated browser context per account, and everything
    that has to be true of a send regardless of which site it happens on.

    Almost none of what follows is platform knowledge. Racing selectors,
    clearing overlays that eat clicks, waiting out a verification puzzle a
    person has to solve, noticing the browser died mid-job, retrying a
    swallowed click, and — hardest won of all — refusing to call something
    sent unless it survives a reload. Each of those came from a failure that
    cost a real target, and none of them is specific to one site.

    What *is* platform knowledge lives in the class attributes below. A new
    site subclasses this, supplies its selectors, and inherits every lesson
    already paid for. Copying the engine instead would fork those lessons on
    day one and let them drift apart quietly.
    """

    #: Which platform's accounts this driver serves.
    PLATFORM = "tiktok"

    #: Can a send be confirmed by reloading and looking again?
    #:
    #: True where the conversation comes back. False on X, where it does
    #: not: reloading a chat lands on a closed-inbox prompt, a read-only
    #: banner, the encryption passcode, or a thread that simply re-renders
    #: without the message — almost anything except the conversation just
    #: written to.
    #:
    #: This was tried, removed, and put back. Removed because the passcode
    #: is a one-time unlock and a locked thread could be detected on its
    #: own; put back because the passcode turned out to be one of several
    #: things the reload lands on, and ten targets that had demonstrably
    #: been delivered were recorded as failures before the pattern was
    #: clear enough to act on.
    #:
    #: What confirms a send without it: the composer cleared, the message
    #: appeared in the thread, it was still there after a pause, and none
    #: of the platform's refusals or recipient blocks were on the page.
    #: Weaker than a reload. Stronger than calling a delivered message
    #: undelivered nine times out of ten.
    CONFIRM_BY_RELOAD = True

    #: Follow every target before messaging it, not only the ones that
    #: turn out to be unreachable without it.
    #:
    #: Off by default: following is a public action on the operator's
    #: account, and on Instagram the Message button is usually there
    #: already, so following first would spend the account's follow budget
    #: to no purpose. On X it is asked for deliberately.
    FOLLOW_BEFORE_MESSAGE = False

    #: Recipient-side blocks, most specific first: (selector key, message).
    #:
    #: All of these mean "this person cannot be reached", which is the
    #: target's business and not the sending account's — so none of them
    #: count against the account's error budget. They are kept apart
    #: because they need different things done about them, and one generic
    #: "unavailable" hides which.
    RECIPIENT_BLOCKS: tuple[tuple[str, str], ...] = ((
        "recipient_refused",
        "does not accept message requests from this account",
    ),)

    #: How long this platform's composer gets to appear, when it needs
    #: more than the shared budget. X's chat UI renders the whole
    #: conversation client-side after the click: measured absent seven
    #: seconds in and present some seconds later, against a shared budget
    #: of fifteen. That margin is what "the composer never opened" was on
    #: the first live send.
    COMPOSER_TIMEOUT_MS: Optional[int] = None

    #: Is the followers list a modal that has to be clicked open?
    #:
    #: True on Instagram, where `/<user>/followers/` renders the profile and
    #: nothing else — the list only exists once the link is clicked. False
    #: on X, where it is an ordinary page with its own URL, no dialog
    #: anywhere in it, and clicking a link to reach it just adds a step
    #: that can fail.
    #:
    #: Getting this wrong is silent: the click lands, no dialog appears, and
    #: the harvest scrolls a modal that does not exist for as long as you
    #: let it, reporting nothing found and no error.
    FOLLOWERS_IN_DIALOG = True

    #: Where the site lives, and where its search is. Only discovery uses
    #: these; messaging navigates to a target's own profile URL.
    SITE_URL = ""
    SEARCH_URL = ""
    #: A search as a URL, with `{q}` for the escaped term. Preferred over
    #: driving the search box, which is a widget with its own opinions.
    SEARCH_QUERY_URL = ""

    #: The site's selector table — the whole platform-specific surface.
    SELECTORS: dict[str, Any] = {}

    #: Consent banners and modals that sit over the controls we need.
    OVERLAY_DISMISS: tuple[str, ...] = OVERLAY_DISMISS

    #: Frame URL fragments that mean "a verification puzzle is in here".
    CHALLENGE_FRAME_HINTS: tuple[str, ...] = CHALLENGE_FRAME_HINTS

    name = "playwright_base"

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
        #: One reusable tab per account. Sending used to open a tab per
        #: target and close it again — a browser launch's worth of work
        #: several hundred times a run, and a visible window flickering
        #: open and shut. The session lives in the context, not the tab, so
        #: navigating the same tab to the next profile is the same thing
        #: with none of the churn.
        self._pages: dict[int, Any] = {}
        self._lock = asyncio.Lock()
        #: Held only while the browser is being launched. Separate from
        #: `_lock`, which `_context_for` holds *across* a startup() call.
        self._startup_lock = asyncio.Lock()

    # --- lifecycle -------------------------------------------------------

    async def startup(self) -> None:
        """Launch the browser, once, however many callers ask at the same time.

        The guard below is a check followed by an await, which is a race as
        soon as anything runs two jobs at a time: both callers see no
        browser, both launch one, and the second overwrites the first —
        leaving a Chromium running that nothing will ever close.
        """
        if self._browser is not None:
            return
        async with self._startup_lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright  # imported lazily

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless, args=list(CHROMIUM_ARGS),
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
        page = self._pages.pop(int(account_id), None)
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001 — closing a dead tab is fine
                pass
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

    async def _page_for(self, account: dict[str, Any]):
        """The tab for this account, reused across targets.

        Safe to share because an account is leased exclusively — two slots
        never hold the same one — and because every send navigates before
        it looks at anything, so nothing survives from the last target.

        A tab that has crashed or been closed by hand is replaced rather
        than handed out broken.
        """
        account_id = int(account["id"])
        page = self._pages.get(account_id)
        if page is not None:
            try:
                if not page.is_closed():
                    return page
            except Exception:  # noqa: BLE001 — treat an unusable tab as gone
                pass
            self._pages.pop(account_id, None)

        context = await self._context_for(account)
        page = await context.new_page()
        self._pages[account_id] = page
        return page

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

        `is_visible` does not honour that timeout by waiting — it answers
        from the page as it stands, and six misses measured 61ms in total.
        Worth writing down, because it looks like a per-selector budget and
        was optimised as one: racing these concurrently saved 40ms and cost
        a behaviour change, so it was put back.
        """
        for selector in keys:
            try:
                if await page.locator(selector).first.is_visible(timeout=250):
                    return True
            except Exception:  # noqa: BLE001 — a miss is expected, try the next
                continue
        return False

    async def _type_message(self, page, editor, message: str) -> None:
        """Type the message, keeping its line breaks inside one message.

        In a chat composer Enter sends. Typing a template with a newline in
        it therefore posts the first line, starts a new message, and posts
        the rest — two messages where one was meant, and a delivery check
        looking for the whole text finds it nowhere.

        Shift+Enter is the line break these composers accept.
        """
        lines = message.split("\n")
        for index, line in enumerate(lines):
            if index:
                await page.keyboard.down("Shift")
                await page.keyboard.press("Enter")
                await page.keyboard.up("Shift")
            if line:
                await editor.type(line, delay=25, timeout=CLICK_MS)

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
        for index, tier in enumerate(tiers):
            # Only the first tier waits for the page. If it has already spent
            # the full budget without a match, the page is settled — every
            # later tier is asking a finished document a question it can
            # answer at once, so giving each of them the same generous budget
            # just multiplies the wait by the number of guesses.
            #
            # Two tiers at 15s each is 30 seconds spent on every profile that
            # has no Message button, and on a run those are common. The cost
            # of cutting it short is a `messaging_unavailable`, which is
            # retryable and gets another run; the cost of not cutting it is
            # paid on every single target.
            budget = timeout_ms if index == 0 else LATER_TIER_MS
            found = await self._first_visible(page, tuple(tier), budget)
            if found is not None:
                return found
        return None

    async def _recipient_block(self, page, target_username: str):
        """The first recipient-side block on this page, as a result, or None.

        Used twice: while waiting for the composer, and again after the
        send. The same notices mean the same thing in both places — this
        person cannot be reached, which is their business and not the
        sending account's — so neither counts against the account.
        """
        for key, reason in self.RECIPIENT_BLOCKS:
            if not await self._present(page, self.SELECTORS.get(key, ())):
                continue
            return MessageResult.failure(
                RESULT_MESSAGING_UNAVAILABLE,
                f"@{target_username} {reason}. Nothing reached them, and "
                f"nothing is wrong with the sending account",
                url=page.url,
                screenshot=await self._save_debug_shot(
                    page, target_username, key.replace("_", "-")
                ),
            )
        return None

    async def _composer_or_block(self, page, target_username: str, timeout_ms: int):
        """Wait for the composer, but stop the moment it cannot come.

        Returns `(editor, blocked)` — exactly one of them set.

        Waiting the full budget for a composer that will never appear is
        pure delay, and on a locked DM it is the whole cost of the job: X
        replaces the composer with "has a closed inbox" straight away and
        the wait then sat there for thirty seconds with the answer already
        on screen.

        So the two are raced. A short poll rather than a single long wait,
        because the question is "which of these appeared first" and the
        blocking notices are static text that `_present` answers without
        waiting at all.
        """
        deadline = time.monotonic() + (timeout_ms / 1000)
        while True:
            editor = await self._first_visible(
                page, self.SELECTORS["message_input"], timeout_ms=COMPOSER_POLL_MS
            )
            if editor is not None:
                return editor, None

            blocked = await self._recipient_block(page, target_username)
            if blocked is not None:
                print(
                    f"[outreach] @{target_username}: the composer will not open "
                    f"— {blocked.error}", flush=True,
                )
                return None, blocked

            if time.monotonic() >= deadline:
                return None, None

    async def _follow_first(self, page, target_username: str) -> bool:
        """Follow this profile before messaging it, if it is not followed yet.

        Distinct from `_follow_to_unlock`, which follows only after a
        Message button turns out to be missing. This is the platform saying
        every target should be followed regardless — on X, because a DM
        from a stranger lands somewhere other than the inbox.

        Never clicks when the profile is already followed or a request is
        pending: that control unfollows or withdraws, and doing either
        would undo the thing this exists to do.
        """
        if await self._present(page, self.SELECTORS.get("already_following", ())):
            return False
        if await self._present(page, self.SELECTORS.get("follow_requested", ())):
            return False

        button = await self._first_visible_tiered(
            page, self.SELECTORS.get("follow_button", ()), timeout_ms=LATER_TIER_MS
        )
        if button is None:
            return False
        if not await self._click(page, button, "follow-button", target_username):
            return False

        print(f"[outreach] followed @{target_username} before messaging", flush=True)
        # Let the button settle before anything reads the profile again —
        # the message control is often re-rendered alongside it.
        await page.wait_for_timeout(SETTLE_MS)
        return True

    async def _follow_to_unlock(self, page, target_username: str):
        """No Message button — try following, and look again.

        Plenty of accounts are not private but still only take messages from
        people they follow. On those the button is genuinely absent until
        the follow lands, and then it appears in place without a reload.
        Writing the target off before trying costs a lead that was reachable
        all along; two were confirmed reachable this way by hand.

        Returns the Message button if following revealed one, else None.

        Following is a public action taken on the operator's account, so it
        happens only here — after the profile has been loaded, read, and
        found to offer no other way through.
        """
        if await self._present(page, self.SELECTORS.get("follow_requested", ())):
            print(
                f"[outreach] @{target_username} already has a follow request "
                f"pending — nothing to do until they accept it",
                flush=True,
            )
            return None
        if await self._present(page, self.SELECTORS.get("already_following", ())):
            # Followed already and still no button: the follow is not what
            # is in the way, and clicking anything here would unfollow them.
            return None

        follow_button = await self._first_visible_tiered(
            page, self.SELECTORS.get("follow_button", ()), timeout_ms=LATER_TIER_MS
        )
        if follow_button is None:
            return None
        if not await self._click(page, follow_button, "follow-button", target_username):
            return None

        # A private account turns Follow into "Requested" and stays shut. The
        # follow is left standing — it is what the request is — but there is
        # nothing to wait for on this visit.
        if await self._present(page, self.SELECTORS.get("follow_requested", ())):
            print(
                f"[outreach] followed @{target_username}, but the account is "
                f"private — the request has to be accepted before a message "
                f"can go anywhere",
                flush=True,
            )
            return None

        message_button = await self._first_visible_tiered(
            page, self.SELECTORS["message_button"], timeout_ms=FOLLOW_UNLOCK_MS
        )
        print(
            f"[outreach] followed @{target_username} — "
            + ("the Message button appeared" if message_button is not None
               else "still no Message button"),
            flush=True,
        )
        return message_button

    async def _dismiss_overlays(self, page) -> list[str]:
        """Click away consent banners and modals covering the page.

        Best-effort and quiet: every selector here is optional, and a miss
        is the normal case once the banner has been accepted for a session.
        """
        dismissed = []
        for selector in self.OVERLAY_DISMISS:
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

        Clicking Message does not always open a composer in place: a site
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
        """Is the site showing a human-verification puzzle?

        Checked on the page itself and across its frames. The puzzle is
        commonly served in an iframe, and `page.locator` does not descend
        into frames, so selectors alone miss it and the profile underneath
        looks perfectly healthy.

        Deliberately only ever *detects*. Solving the puzzle is a person's
        job — `outreach-watch.sh` puts the browser on screen for exactly
        that.
        """
        if await self._present(page, self.SELECTORS["verification_challenge"]):
            return True
        try:
            for frame in page.frames:
                if frame is page.main_frame:
                    continue
                url = (frame.url or "").lower()
                if any(hint in url for hint in self.CHALLENGE_FRAME_HINTS):
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

    async def _message_in_thread(self, page, message: str) -> bool:
        """Is the message on the page — in the thread if we can tell, else
        anywhere?

        The thread's own items are checked first because they are the honest
        place to look. But a miss there is NOT taken as proof of failure:
        those attributes are the first thing a redesign renames, and a false
        negative here costs a duplicate DM on the retry. So the page body
        remains the fallback, exactly as before.

        What actually catches a phantom send is not where we look but how
        often — see `_delivery_holds`.
        """
        def flatten(value: str) -> str:
            """Compare words, not whitespace.

            A message with a line break in it is one string here and a
            `<br>`, a nested div, or a newline in the rendered thread — and
            a literal `\n` from the template matched none of them. Every
            multi-line template failed this check while being delivered
            perfectly well.
            """
            return " ".join((value or "").split())

        needle = flatten(message)[:60]
        if not needle:
            return False
        for selector in self.SELECTORS["sent_confirmation"]:
            try:
                # One round trip for the whole selector. Asking each element
                # for its text separately costs a call apiece and times out
                # on threads long enough to matter.
                texts = await page.eval_on_selector_all(
                    selector, "els => els.slice(-40).map(e => e.innerText || '')"
                )
            except Exception:  # noqa: BLE001 — try the next shape
                continue
            for text in texts:
                if needle in flatten(text):
                    return True
        try:
            body = (await page.locator("body").inner_text(timeout=3000)) or ""
        except Exception:  # noqa: BLE001
            return False
        return needle in flatten(body)

    async def _delivery_holds(
        self, page, message: str, target: dict[str, Any], username: str
    ) -> bool:
        """Is the message in the thread, and does it stay there?

        An optimistic render satisfies a single check and then vanishes: a
        campaign reported `sent` and the recipient's thread was empty, because
        the text was on the page at the moment it was looked at and gone
        afterwards. So it is checked, left alone, and checked again — a
        message the platform actually took is still there the second time.
        """
        if not await self._message_in_thread(page, message):
            return False
        await page.wait_for_timeout(SETTLE_MS)
        if not await self._message_in_thread(page, message):
            print(
                "[outreach] the message appeared in the thread and then "
                "disappeared — not delivered",
                flush=True,
            )
            return False

        if not self.CONFIRM_BY_RELOAD:
            print("[outreach] delivery confirmed in the thread "
                  "(this platform does not show it again on reload)", flush=True)
            return True

        # The only check that cannot be satisfied by the page alone.
        #
        # Two "sent" results were recorded against a conversation that was
        # empty when a person opened it. The text was in the thread, it was
        # still there 2.5s later, and TikTok had kept none of it — the DOM
        # simply cannot tell an accepted message from a discarded optimistic
        # render. A reload throws away everything the client made up and
        # shows only what the server will give back.
        try:
            await page.reload(wait_until="domcontentloaded", timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[outreach] could not reload to confirm delivery "
                f"({type(exc).__name__}) — refusing to claim it sent",
                flush=True,
            )
            return False

        # Give the reloaded page a moment to render its thread — but not the
        # composer's budget, which is what this used to take.
        #
        # On Instagram the thread is never on a reloaded profile: the send
        # happens in a dock, and reloading returns a bare profile. So these
        # selectors never matched, and every successful send paid the full
        # fifteen seconds finding that out before falling through to the
        # step that actually works. It was the single largest fixed cost in
        # a send, and it was pure waiting.
        #
        # Cutting it short is safe in a way most timeout cuts are not: if
        # the thread genuinely needed longer, the miss falls through to
        # reopening the conversation, which asks the server directly. The
        # fallback is the same one that already handles this, not a failure.
        await self._first_visible(
            page, self.SELECTORS["sent_confirmation"], timeout_ms=CONFIRM_RENDER_MS
        )
        if not await self._message_in_thread(page, message):
            # A locked thread is not an absent message.
            #
            # X asks for its encryption passcode once per browser, and a
            # worker starting from a stored session has not given it — so
            # the reload lands on "Enter Passcode" and the conversation is
            # not shown to anyone. Reading that as "the platform did not
            # keep it" turned delivered messages into failures and queued
            # them to be sent again.
            #
            # The evidence from before the reload still stands: the
            # composer cleared, the message was in the thread, it was still
            # there after a pause, and no refusal was on the page. Weaker
            # than a reload — and the alternative is calling a delivered
            # message undelivered every time.
            if await self._present(page, self.SELECTORS["verification_challenge"]):
                print(
                    "[outreach] the conversation is locked behind a challenge "
                    "after the reload — accepting what was seen before it",
                    flush=True,
                )
                return True

            # A reload only proves anything if the conversation is on the
            # page it reloaded. Instagram sends from a chat dock over the
            # profile, so reloading returns a bare profile with no thread on
            # it at all — a real, delivered message looked identical to a
            # discarded one. Reopening the conversation asks the server for
            # it again, which is the same proof by a different route.
            if not await self._reopen_conversation(page, target, username):
                print(
                    "[outreach] the message did not survive a reload, and the "
                    "conversation could not be reopened — not delivered",
                    flush=True,
                )
                return False
            if not await self._message_in_thread(page, message):
                print(
                    "[outreach] the reopened conversation does not contain the "
                    "message — the platform did not keep it",
                    flush=True,
                )
                return False
            print(
                "[outreach] delivery confirmed: the message is in the "
                "conversation after reopening it",
                flush=True,
            )
            return True

        print("[outreach] delivery confirmed: the message survived a reload", flush=True)
        return True

    async def _attach_image(self, page, path: str, username: str) -> Optional[str]:
        """Put an image in the open composer. None on success, else why not.

        Driven by a file input rather than by clicking the paperclip: the
        picker a click opens is an OS dialog, which Playwright cannot touch.
        Setting the input directly is both possible and the only thing that
        works — hidden inputs included, which is how these are usually built.

        A platform with no `attach_image` selectors cannot send images at
        all. That is reported, not ignored: sending the text alone and
        calling it done would be a quieter version of claiming a delivery
        that did not happen.
        """
        selectors = self.SELECTORS.get("attach_image") or ()
        if not selectors:
            return (
                f"{self.PLATFORM} messages cannot carry an image — its web "
                f"composer has no attachment control"
            )
        if not Path(path).is_file():
            return f"The campaign's image is missing from disk ({path})"

        for selector in selectors:
            try:
                await page.set_input_files(selector, path, timeout=CLICK_MS)
            except Exception:  # noqa: BLE001 — try the next shape
                continue
            print(f"[outreach] attached an image for @{username}", flush=True)
            # The upload has to reach the composer before anything submits.
            await page.wait_for_timeout(SETTLE_MS)
            return None
        return "Could not find anywhere to attach an image in the composer"

    async def _reopen_conversation(self, page, target: dict[str, Any], username: str) -> bool:
        """Open this target's conversation again, from the profile.

        Used only to confirm a delivery. Clicking Message re-fetches the
        conversation from the platform, so what appears in it came from the
        server rather than from anything this page invented.
        """
        editor = await self._retry_message_click(page, target, username)
        if editor is None:
            return False
        # Give the history a moment to populate — the composer appears
        # before the messages above it do.
        await page.wait_for_timeout(SETTLE_MS)
        return True

    async def _reload_and_settle(self, page, url: str) -> None:
        """Reload the profile and wait for its shell again.

        A site error page carries a Refresh button for
        a reason — the state is transient. Reloading is the same move, and
        it is what stands between a temporary site error and a target being
        written off.
        """
        print(f"[outreach] reloading {url} after a site error", flush=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 — the caller reports the outcome
            print(f"[outreach] reload failed: {type(exc).__name__}: {exc}", flush=True)
            return
        await self._first_visible(
            page, self.SELECTORS["profile_loaded"], timeout_ms=PROFILE_READY_MS
        )

    async def _retry_message_click(self, page, target: dict[str, Any], username: str):
        """Click Message once more when the first click opened nothing.

        A challenge thrown by the click consumes it: the page is healthy
        afterwards, the button is right there, but nothing was ever opened.
        Clearing the puzzle does not replay the click, so the composer wait
        times out and the page gets blamed for a click it never received.

        Deliberately not conditional on having *seen* the challenge. The
        puzzle can come and go inside the composer wait — it did exactly
        that in testing, vanishing before the check ran — and any swallowed
        click looks the same from here. One extra click on a control we
        already found is cheap; losing the job is not.
        """
        button = await self._first_visible_tiered(
            page, self.SELECTORS["message_button"], timeout_ms=MESSAGE_BUTTON_MS
        )
        if button is None:
            print(
                "[outreach] no Message button to retry after the puzzle cleared",
                flush=True,
            )
            return None
        if not await self._click(page, button, "message-button (after puzzle)", username):
            return None

        editor = await self._first_visible(
            page, self.SELECTORS["message_input"],
                timeout_ms=self.COMPOSER_TIMEOUT_MS or COMPOSER_MS
        )
        if editor is None and await self._present(page, self.SELECTORS["messages_view"]):
            if await self._open_thread(page, target):
                editor = await self._first_visible(
                    page, self.SELECTORS["message_input"],
                timeout_ms=self.COMPOSER_TIMEOUT_MS or COMPOSER_MS
                )
        if editor is not None:
            print("[outreach] composer opened on the retry after the puzzle", flush=True)
        return editor

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

            page = await self._page_for(account)

            # 1-2. Navigate to the target profile.
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            except PlaywrightTimeout:
                return MessageResult.failure(
                    RESULT_NAVIGATION_TIMEOUT,
                    f"Timed out loading {url}",
                    url=url,
                )

            # These profiles are client-rendered shells: domcontentloaded
            # fires long before the action buttons exist. Give it a beat to
            # paint something recognisable, or every check below races an
            # empty page and reports "no Message button" on profiles that
            # plainly have one.
            await self._first_visible(
                page, self.SELECTORS["profile_loaded"], timeout_ms=PROFILE_READY_MS
            )

            if await self._present(page, self.SELECTORS["profile_missing"]):
                return MessageResult.failure(
                    RESULT_PROFILE_UNAVAILABLE,
                    "Profile not found or private",
                    url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "profile-missing"),
                )
            if await self._present(page, self.SELECTORS["login_wall"]):
                # The stored session no longer authenticates us.
                return MessageResult.failure(
                    RESULT_SESSION_EXPIRED,
                    "Session expired — the site is showing its login wall",
                    url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "login-wall"),
                )
            if await self._present(page, self.SELECTORS["rate_limited"]):
                return MessageResult.failure(
                    RESULT_RATE_LIMITED, "Platform is rate limiting this account", url=url,
                    screenshot=await self._save_debug_shot(page, target_username, "rate-limited"),
                )
            # Before anything is concluded about the target: is there a
            # verification puzzle over this page? It sits on top of a
            # completely normal profile, so every check below misreads it —
            # the button is found but unclickable, or not found at all, and
            # the target gets skipped as "doesn't accept DMs".
            if await self._challenge_present(page):
                if not await self._challenge_cleared_by_hand(page, target_username):
                    return MessageResult.failure(
                        RESULT_CHALLENGE_REQUIRED,
                        "TikTok is asking this account to pass a verification "
                        "puzzle. Nothing is wrong with the target — a person has "
                        "to solve it (deploy/outreach-watch-mac.sh shows the "
                        "browser), then resume the account",
                        url=url,
                        screenshot=await self._save_debug_shot(
                            page, target_username, "challenge"
                        ),
                    )
                # What sits underneath a cleared puzzle is regularly
                # TikTok's own error page rather than the profile.
                await self._reload_and_settle(page, url)

            # 2b. Follow first, if asked to, and let the message wait.
            #
            # A follow and a DM in the same second is not what a person looks
            # like, and TikTok decides who may message whom partly on the
            # follow relationship — so the message is held back rather than
            # sent now. The job is requeued to run after the wait, which
            # keeps the browser free instead of sleeping with a lease open.
            follow_wait = int(target.get("follow_wait_seconds") or 0)
            if follow_wait > 0 and not await self._present(
                page, self.SELECTORS["already_following"]
            ):
                follow_button = await self._first_visible_tiered(
                    page, self.SELECTORS["follow_button"], timeout_ms=MESSAGE_BUTTON_MS
                )
                if follow_button is not None and await self._click(
                    page, follow_button, "follow-button", target_username
                ):
                    print(
                        f"[outreach] followed @{target_username} — holding the "
                        f"message for {follow_wait}s",
                        flush=True,
                    )
                    return MessageResult.failure(
                        RESULT_FOLLOW_PENDING,
                        f"Followed @{target_username}. The message is held for "
                        f"{follow_wait}s so the follow lands first",
                        url=url,
                    )
                print(
                    f"[outreach] no Follow control on @{target_username} — "
                    f"messaging without following",
                    flush=True,
                )

            # 2c. Follow first, where the platform asks for it.
            if self.FOLLOW_BEFORE_MESSAGE:
                await self._follow_first(page, target_username)

            # 3-4. Is the messaging interface available, and open it.
            message_button = await self._first_visible_tiered(
                page, self.SELECTORS["message_button"], timeout_ms=MESSAGE_BUTTON_MS
            )
            if message_button is None and self._page_is_gone(page):
                return MessageResult.failure(
                    RESULT_ABORTED,
                    "The browser closed before the Message button could be found "
                    "— most likely the worker was stopped mid-job. Nothing was "
                    "learned about this target",
                    url=url,
                )
            if message_button is None and await self._present(page, self.SELECTORS["site_error"]):
                # Not the target's doing: TikTok replaced the whole profile
                # with its own error page, which has a Refresh button on it
                # precisely because the state is transient. Take the hint.
                await self._reload_and_settle(page, url)
                message_button = await self._first_visible_tiered(
                    page, self.SELECTORS["message_button"], timeout_ms=MESSAGE_BUTTON_MS
                )
                if message_button is None and await self._present(page, self.SELECTORS["site_error"]):
                    return MessageResult.failure(
                        RESULT_UNEXPECTED_PAGE,
                        "TikTok served its own \"Something went wrong\" page instead "
                        "of the profile, and it was still there after a reload. "
                        "Nothing is known about this target — worth another run",
                        url=url,
                        screenshot=await self._save_debug_shot(
                            page, target_username, "site-error"
                        ),
                    )

            if message_button is None and target.get("follow_to_unlock"):
                # Before writing this target off: some accounts take messages
                # only from people they follow, and the button appears once
                # the follow lands.
                message_button = await self._follow_to_unlock(page, target_username)

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

            editor, blocked = await self._composer_or_block(
                page, target_username,
                timeout_ms=self.COMPOSER_TIMEOUT_MS or COMPOSER_MS,
            )
            if blocked is not None:
                return blocked

            # Clicking Message can hand off to the messages app instead of
            # opening a box in place. When the thread does not come with it
            # we land on the inbox — a list of every conversation and no
            # composer at all — so pick the target's own thread out of it.
            if editor is None and await self._present(page, self.SELECTORS["messages_view"]):
                if await self._open_thread(page, target):
                    editor = await self._first_visible(
                        page, self.SELECTORS["message_input"],
                timeout_ms=self.COMPOSER_TIMEOUT_MS or COMPOSER_MS
                    )

            if editor is None and self._page_is_gone(page):
                return MessageResult.failure(
                    RESULT_ABORTED,
                    "The browser closed before the composer could open — most "
                    "likely the worker was stopped mid-job",
                    url=url,
                )
            if editor is None and await self._present(page, self.SELECTORS["login_wall"]):
                return MessageResult.failure(
                    RESULT_SESSION_EXPIRED, "Session expired at the message step", url=url
                )

            if editor is None and await self._challenge_present(page):
                if not await self._challenge_cleared_by_hand(page, target_username):
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
                # The puzzle ate the click that was meant to open the
                # composer, and clearing it does not replay that click — so
                # waiting for a composer that was never asked for just times
                # out and reports "composer never opened" on a profile whose
                # Message button is sitting there untouched. Ask again.
                editor = await self._retry_message_click(page, target, target_username)

            # The click may also have been swallowed by a puzzle that came
            # and went while we waited, leaving nothing to detect above.
            if editor is None and not self._page_is_gone(page):
                editor = await self._retry_message_click(page, target, target_username)

            if editor is None:
                on_inbox = await self._present(page, self.SELECTORS["messages_view"])
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
            # Explicit budget: without one this falls through to the
            # context default of thirty seconds, and a composer that went
            # stale between being found and being clicked then costs half a
            # minute per target. Seen in production as
            # "TimeoutError: Locator.click: Timeout 30000ms".
            await editor.click(timeout=CLICK_MS)
            await self._type_message(page, editor, message)

            # 5b. The campaign's image, if it has one. Before submitting:
            # the composer sends text and attachment together, and an image
            # added afterwards would be a second, separate message.
            attachment = target.get("attachment_path")
            if attachment:
                problem = await self._attach_image(page, attachment, target_username)
                if problem:
                    return MessageResult.failure(
                        RESULT_UNEXPECTED_PAGE,
                        f"{problem}. Nothing was sent — remove the image from "
                        f"the campaign, or send it from a platform that "
                        f"supports one",
                        url=page.url,
                        screenshot=await self._save_debug_shot(
                            page, target_username, "attach-failed"
                        ),
                    )

            # 6. Submit.
            send_button = await self._first_visible(page, self.SELECTORS["send_button"], timeout_ms=4000)
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
            if await self._present(page, self.SELECTORS["rate_limited"]):
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

            # Refused by this recipient, not by the platform. "They don't
            # allow new message requests from everyone" is a setting on
            # their account and says nothing about ours — filing it as a
            # refusal would count it against the sending account's error
            # budget and eventually pause a perfectly healthy account
            # because a few strangers keep their inbox closed.
            #
            # It is the same situation as a profile with no Message button:
            # this person cannot be reached from here, try the next one.
            blocked = await self._recipient_block(page, target_username)
            if blocked is not None:
                return blocked

            # An explicit refusal is judged before anything else: TikTok
            # has already said it did not send this, so there is nothing
            # for a persistence check to add.
            if await self._present(page, self.SELECTORS["message_refused"]):
                return MessageResult.failure(
                    RESULT_MESSAGE_REFUSED,
                    "TikTok put the message in the thread and then refused to "
                    "deliver it: it says the message has not been sent. Nothing "
                    "reached the target. The wording and the account standing "
                    "are what to change, not the target",
                    url=page.url,
                    screenshot=await self._save_debug_shot(
                        page, target_username, "message-refused"
                    ),
                )

            if not await self._delivery_holds(page, message, target, target_username):
                # Ask again why, now that the reload has happened. X puts
                # its closed-inbox prompt up only once the conversation is
                # re-opened, so the block that explains the whole job is
                # not on screen at the point the send was attempted — and
                # every one of them was being reported as the generic "the
                # message is not in the conversation".
                blocked = await self._recipient_block(page, target_username)
                if blocked is not None:
                    return blocked
                await self._save_debug_shot(page, target_username, "not-in-thread")
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    "The composer emptied but the message is not in the "
                    "conversation, or did not stay there — nothing was "
                    "confirmed delivered",
                    url=page.url,
                )

            # Delivered — but say where it landed, when the platform has
            # told us. X routes a message to someone who does not follow
            # you into their requests rather than their inbox, which is
            # worth knowing and is not a failure.
            if await self._present(page, self.SELECTORS.get("delivered_note", ())):
                print(
                    f"[outreach] delivered to @{target_username}, though the "
                    f"platform says it will not land in their inbox — they do "
                    f"not follow this account",
                    flush=True,
                )
            await self._save_debug_shot(page, target_username, "sent")
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
            # 9. The tab stays open for the next target — closing it and
            # opening another is what this used to do, and it bought
            # nothing: the session is in the context, and the next send
            # navigates before it reads anything.
            #
            # A tab that died mid-job is dropped, so the next send builds a
            # fresh one instead of inheriting the corpse.
            if page is not None and self._page_is_gone(page):
                self._pages.pop(int(account.get("id") or 0), None)

    # --- session capture -------------------------------------------------

    # --- discovery -------------------------------------------------------
    #
    # Finding profiles, as opposed to messaging them. Same context handling,
    # same overlay clearing, same puzzle waiting; a different set of pages.
    #
    # This is browsing, at a person's pace, for things a person could see —
    # but a great deal of it, which is what makes it the likelier way to
    # lose an account. The caller enforces the caps; what is here refuses to
    # go faster than it is told and stops the moment it is asked to.

    async def discover_profiles(
        self,
        account: dict[str, Any],
        *,
        hashtags: tuple[str, ...] = (),
        terms: tuple[str, ...] = (),
        limit: int = 50,
        include_commenters: bool = False,
        include_likers: bool = False,
        interval_seconds: float = 6.0,
        scroll_rounds: int = 4,
        should_stop: Optional[Any] = None,
        on_found: Optional[Any] = None,
        exclude: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """Collect public profiles matching these hashtags and search terms.

        Returns `[{username, profile_url, display_name, source}]`, deduped.
        Stops at `limit`, or as soon as `should_stop()` says to.

        Nothing here logs in, follows, likes or comments — it reads pages
        the account can already see.

        `include_commenters` costs nothing extra: commenters are on the
        post page the author was read from. `include_likers` costs one more
        page load per post, because the like list lives behind its own URL.
        Both find people who engaged rather than merely posted, which is
        usually the better list — and both mean opening more pages, which
        is the thing that gets a discovery account noticed.
        """
        if not self.SELECTORS.get("search_input") and not self.SELECTORS.get("hashtag_url"):
            raise DiscoveryUnsupported(
                f"{self.PLATFORM} discovery is not implemented in this driver."
            )

        found: dict[str, dict[str, Any]] = {}
        context = await self._context_for(account)
        page = await context.new_page()

        def done() -> bool:
            if len(found) >= limit:
                return True
            return bool(should_stop and should_stop())

        skip = exclude or set()

        async def remember(username: str, source: str, display_name: str = "") -> None:
            username = (username or "").strip().lstrip("@")
            # Someone already found, here or in an earlier search, is not a
            # new lead — and must not consume any of the budget.
            if not username or username in found or username in skip:
                return
            found[username] = {
                "username": username,
                "profile_url": self.profile_url(username),
                "display_name": display_name or None,
                "source": source,
            }
            if on_found:
                await on_found(found[username])

        # Both surfaces answer the same way. A hashtag URL redirects into
        # search, and search returns *posts* — not accounts. People are
        # found by opening a post and reading who wrote it, which is why
        # every query below costs a page load per profile.
        queries: list[tuple[str, str]] = []
        for term in terms:
            if self.SEARCH_QUERY_URL:
                queries.append((f"search:{term}", self.SEARCH_QUERY_URL.format(
                    q=quote_plus(term))))
        for tag in hashtags:
            queries.append((f"#{tag}", self.hashtag_url(tag)))

        try:
            for label, url in queries:
                if done():
                    break
                # A search page occasionally lists accounts directly. Cheap
                # to take when it does.
                posts = await self._posts_for_query(page, url, limit - len(found))
                for entry in await self._collect_search_results(page, limit - len(found)):
                    await remember(entry["username"], label, entry.get("name", ""))

                for post_url in posts:
                    if done():
                        break
                    people = await self._people_on_post(
                        page, post_url, scroll_rounds)
                    if people:
                        # First is whoever posted it; the rest commented.
                        await remember(people[0], label, "")
                        if include_commenters:
                            for name in people[1:]:
                                await remember(name, f"comments:{label}", "")
                                if done():
                                    break
                    if include_likers and not done():
                        for name in await self._post_likers(
                            page, post_url, scroll_rounds
                        ):
                            await remember(name, f"likes:{label}", "")
                            if done():
                                break
                    await page.wait_for_timeout(int(interval_seconds * 1000))
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

        return list(found.values())

    async def profile_summary(self, page, username: str) -> dict[str, Any]:
        """Name, bio and follower count for one profile, or empty fields.

        Costs a page load per lead, which is why it is optional. Without it
        a lead is a username and nothing else, and the relevance pass has
        nothing to read — it skips every one of them, silently.
        """
        return {"display_name": None, "bio": None, "followers": None}

    def profile_url(self, username: str) -> str:
        """Where this platform keeps a profile. Overridden per platform."""
        raise DiscoveryUnsupported(f"{self.PLATFORM} has no profile URL template.")

    async def _search_accounts(self, page, term: str, limit: int) -> list[dict[str, str]]:
        """Accounts the site's own search returns for this term.

        By URL where the site has one. Driving the search box means clicking
        it, and Instagram's is a button that opens a panel with the real
        input behind it — the input is visible and enabled and something
        else takes the click, which is thirty seconds of retrying per term
        for nothing. A URL asks the same question and skips the widget.
        """
        if limit <= 0:
            return []
        try:
            if self.SEARCH_QUERY_URL:
                await page.goto(
                    self.SEARCH_QUERY_URL.format(q=quote_plus(term)),
                    wait_until="domcontentloaded", timeout=self._timeout,
                )
                await self._dismiss_overlays(page)
                await page.wait_for_timeout(SETTLE_MS)
                return await self._collect_search_results(page, limit)

            selectors = self.SELECTORS.get("search_input") or ()
            if not selectors:
                return []
            await page.goto(self.SEARCH_URL, wait_until="domcontentloaded",
                            timeout=self._timeout)
            await self._dismiss_overlays(page)
            box = await self._first_visible(page, tuple(selectors), timeout_ms=COMPOSER_MS)
            if box is None:
                return []
            # Force through whatever is sitting on top, as the message
            # button does — a covered control is the normal case here.
            if not await self._click(page, box, "search-box", term):
                return []
            await box.type(term, delay=40, timeout=CLICK_MS)
            # Results arrive as you type; there is nothing to submit.
            await page.wait_for_timeout(SETTLE_MS)
            return await self._collect_search_results(page, limit)
        except Exception as exc:  # noqa: BLE001 — a bad term is not fatal
            print(f"[discovery] search {term!r} failed: {type(exc).__name__}: {exc}",
                  flush=True)
            return []

    async def _collect_search_results(self, page, limit: int) -> list[dict[str, str]]:
        selectors = self.SELECTORS.get("search_result") or ()
        out: list[dict[str, str]] = []
        for selector in selectors:
            try:
                links = page.locator(selector)
                for i in range(min(await links.count(), limit * 3)):
                    href = await links.nth(i).get_attribute("href") or ""
                    username = self.username_from_url(href)
                    if username:
                        out.append({"username": username, "name": ""})
                    if len(out) >= limit:
                        return out
            except Exception:  # noqa: BLE001 — try the next shape
                continue
        return out

    async def _posts_for_query(self, page, url: str, limit: int) -> list[str]:
        """Post URLs from a search or hashtag page.

        Waits for the grid rather than sleeping at it: these pages render
        client-side well after `domcontentloaded`, and a fixed pause is
        either too short to see anything or too long on every page.
        """
        if not self.SELECTORS.get("post_link") or limit <= 0:
            return []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            await self._dismiss_overlays(page)
            await self._first_visible(
                page, tuple(self.SELECTORS["post_link"]), timeout_ms=COMPOSER_MS
            )
            urls: list[str] = []
            for selector in self.SELECTORS["post_link"]:
                try:
                    links = page.locator(selector)
                    for i in range(min(await links.count(), limit * 2)):
                        href = await links.nth(i).get_attribute("href") or ""
                        if href and href not in urls:
                            urls.append(href)
                        if len(urls) >= limit:
                            return urls
                except Exception:  # noqa: BLE001
                    continue
            return urls
        except Exception as exc:  # noqa: BLE001
            print(f"[discovery] {url} failed: {type(exc).__name__}: {exc}", flush=True)
            return []

    async def _people_on_post(self, page, post_url: str,
                              scroll_rounds: int = 0) -> list[str]:
        """Everyone named on a post, in document order.

        The author comes first and commenters follow, because that is the
        order the page lists them in. One selector serves both: a post page
        has no `article`, no `header` and no comment list to scope to, and
        every attempt to be more specific than "profile links inside main"
        matched nothing at all.
        """
        return await self._profile_links(
            page, self._absolute(post_url),
            self.SELECTORS.get("post_people") or (), scroll_rounds,
        )

    async def _post_likers(self, page, post_url: str,
                           scroll_rounds: int = 0) -> list[str]:
        """Who liked a post.

        Instagram keeps this behind a dialog, but the dialog has a URL of
        its own — asking for it directly avoids clicking a control whose
        label is a number that changes.
        """
        selectors = self.SELECTORS.get("liker") or ()
        if not selectors:
            return []
        url = self._absolute(post_url).rstrip("/") + "/liked_by/"
        return await self._profile_links(page, url, selectors, scroll_rounds)

    async def _collect_profile_links(self, page, selectors) -> list[str]:
        """Profile handles currently rendered, in document order, deduped.

        Every href in one call. Asking Playwright for them one at a time is
        a round trip each, so a dialog holding a thousand rows took long
        enough per pass to be useless — it was most of why scrolling a long
        list crawled, and why it appeared to stop making progress.
        """
        names: list[str] = []
        for selector in selectors:
            try:
                hrefs = await page.eval_on_selector_all(
                    selector,
                    "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
                )
            except Exception:  # noqa: BLE001 — try the next shape
                continue
            for href in hrefs:
                username = self.username_from_url(href)
                if username and username not in names:
                    names.append(username)
            if names:
                break
        return names

    async def _load_more(self, page) -> None:
        """Scroll whatever holds the list, and press any "load more" control.

        Comments and likes are both paged: the page renders a dozen and
        fetches the rest as you scroll. Reading what happens to be on screen
        gets the first handful of each and nothing else, which is why a
        search burned through posts finding twelve people at a time.

        Scrolls the dialog when one is open — the likes list is inside it
        and the page behind does not move — and the window otherwise.
        """
        for selector in self.SELECTORS.get("load_more") or ():
            try:
                control = page.locator(selector).first
                if await control.is_visible(timeout=300):
                    await control.click(timeout=CLICK_MS)
                    await page.wait_for_timeout(SCROLL_PAUSE_MS)
            except Exception:  # noqa: BLE001 — it is a convenience, not a step
                pass
        # A wheel event, not `scrollTop = scrollHeight`. These lists fetch
        # their next page when a sentinel near the bottom comes into view,
        # and jumping straight to the end skips past it without ever firing
        # the observer: a post with 718 likes gave up 99 and stopped, no
        # matter how many times it was "scrolled".
        moved = False
        for selector in self.SELECTORS.get("scroll_container") or ():
            try:
                box = await page.locator(selector).first.bounding_box(timeout=400)
            except Exception:  # noqa: BLE001
                box = None
            if box:
                await page.mouse.move(
                    box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                )
                moved = True
                break
        try:
            if not moved:
                size = page.viewport_size or {"width": 1280, "height": 800}
                await page.mouse.move(size["width"] / 2, size["height"] / 2)
            # One turn. Reaching the bottom is what asks for the next page;
            # scrolling again while it loads achieves nothing, and the
            # caller waits for the result rather than guessing at a pause.
            await page.mouse.wheel(0, 2400)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(SCROLL_POLL_MS)

    async def discover_followers(
        self,
        account: dict[str, Any],
        *,
        seeds: tuple[str, ...],
        limit: int = 50,
        interval_seconds: float = 6.0,
        scroll_rounds: int = 12,
        should_stop: Optional[Any] = None,
        on_found: Optional[Any] = None,
        exclude: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """Collect the people following each of these accounts.

        A far more direct list than a hashtag: everyone here chose to follow
        something specific. It is also the most conspicuous thing in this
        module — one account paging through another's followers is the
        classic shape of scraping, so the same caps and pauses apply and the
        budget is shared evenly across the seeds rather than drained on the
        first.
        """
        found: dict[str, dict[str, Any]] = {}
        context = await self._context_for(account)
        page = await context.new_page()

        def done() -> bool:
            return len(found) >= limit or bool(should_stop and should_stop())

        try:
            seeds = tuple(s.strip().lstrip("@") for s in seeds if s.strip())
            if not seeds:
                return []
            # Even shares, so three seeds give three lists rather than one.
            share = max(limit // len(seeds), 1)
            skip = exclude or set()
            for seed in seeds:
                if done():
                    break
                # Ask for more than the share, and scroll deep enough to
                # get there. A followers list comes back in the same order
                # every time, so everyone already known sits at the top of
                # it: finding new people means scrolling past all of them
                # first. Depth based on the share alone stops inside
                # familiar territory and reports nothing new — which looks
                # like the account having no more followers.
                reach = share + len(skip)
                for username in await self.account_followers(
                    page, seed, limit=reach,
                    scroll_rounds=max(scroll_rounds, reach // 10 + 20),
                ):
                    if username in found or username in skip:
                        continue
                    if len([f for f in found.values()
                            if f["source"] == f"followers:@{seed}"]) >= share:
                        break
                    found[username] = {
                        "username": username,
                        "profile_url": self.profile_url(username),
                        "display_name": None,
                        "source": f"followers:@{seed}",
                    }
                    if on_found:
                        await on_found(found[username])
                    if done():
                        break
                await page.wait_for_timeout(int(interval_seconds * 1000))
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
        return list(found.values())

    def followers_urls(self, username: str) -> tuple[str, ...]:
        """Every page that lists this account's followers, in order.

        A tuple rather than one URL because X splits the list across tabs —
        Verified Followers and Followers are separate pages, and reading
        only the second one silently drops everyone in the first. They are
        harvested in sequence and merged; the overlap between them costs
        nothing, since names are deduped.

        Only consulted when `FOLLOWERS_IN_DIALOG` is false — a platform
        whose list is a modal never reaches this.
        """
        return (f"{self.profile_url(username)}/followers",)

    async def account_followers(self, page, username: str, limit: int,
                                scroll_rounds: int = 8) -> list[str]:
        """Who follows this account.

        Not by URL. `/<user>/followers/` renders the profile and nothing
        else — the list is a modal that only opens when the link on a
        loaded profile is clicked, so navigating straight to it returns a
        page with no dialog on it at all. The likes list does open by URL,
        which is exactly why this was worth checking rather than assuming.
        """
        if limit <= 0:
            return []
        try:
            if not self.FOLLOWERS_IN_DIALOG:
                # Ordinary pages. Ask for each directly rather than loading
                # the profile and hunting for a link to click, and merge
                # them — one account's followers can be split across
                # several tabs, and reading one drops the rest.
                merged: dict[str, None] = {}
                for url in self.followers_urls(username):
                    if len(merged) >= limit:
                        break
                    await page.goto(url, wait_until="domcontentloaded",
                                    timeout=self._timeout)
                    await self._dismiss_overlays(page)
                    if await self._present(page, self.SELECTORS["profile_missing"]):
                        print(f"[discovery] @{username} does not exist, or shows "
                              f"no followers", flush=True)
                        return []
                    before = len(merged)
                    for name in await self._links_in_open_dialog(
                        page, scroll_rounds, wanted=limit - len(merged)
                    ):
                        if name != username:
                            merged.setdefault(name)
                    tab = url.rstrip("/").rsplit("/", 1)[-1]
                    print(f"[discovery] {tab}: {len(merged) - before} new "
                          f"({len(merged)} so far)", flush=True)
                return list(merged)[:limit]
            else:
                selectors = self.SELECTORS.get("followers_link") or ()
                if not selectors:
                    return []
                await page.goto(self.profile_url(username),
                                wait_until="domcontentloaded", timeout=self._timeout)
                await self._dismiss_overlays(page)
                link = await self._first_visible(
                    page, tuple(selectors), timeout_ms=COMPOSER_MS
                )
                if link is None:
                    print(f"[discovery] no followers link on @{username} — private, "
                          f"or it does not show its followers", flush=True)
                    return []
                if not await self._click(page, link, "followers-link", username):
                    return []
            names = await self._links_in_open_dialog(page, scroll_rounds, wanted=limit)
            # An account's own handle is in the profile behind the dialog.
            return [n for n in names if n != username][:limit]
        except Exception as exc:  # noqa: BLE001 — one bad seed is not fatal
            print(f"[discovery] followers of @{username} failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return []

    async def _dialog_height(self, page) -> int:
        """How tall the scrolling list is right now, in pixels.

        A better progress signal than the number of names: when a fetch
        lands the list gets taller immediately, while the names in it may
        be ones already seen. Judging progress by names alone means a run
        that is scrolling correctly through familiar territory looks stuck.
        """
        try:
            container = (self.SELECTORS.get("scroll_container") or ("body",))[0]
            return int(await page.evaluate(
                """(sel) => {
                    const d = document.querySelector(sel);
                    if (!d) return document.body.scrollHeight || 0;
                    // Every candidate, and the tallest wins — rather than
                    // preferring the inner ones.
                    //
                    // Instagram's list scrolls inside the modal, so an
                    // inner box is the thing that grows. X's grows the
                    // container itself, and the only inner box that
                    // qualifies is a 166px decoration that never changes —
                    // so preferring inner boxes returned 166 every round,
                    // for ever, and the harvest had no progress signal at
                    // all. It still collected; it just could not tell a
                    // list still loading from one that had ended, and gave
                    // up at 297 of 400.
                    //
                    // Deliberately not the document: behind Instagram's
                    // modal sits a page of roughly fixed height, and
                    // including it would mask the growth it is here to see.
                    const heights = Array.from(d.querySelectorAll('*'))
                        .filter(el => el.scrollHeight > el.clientHeight + 40)
                        .map(el => el.scrollHeight);
                    heights.push(d.scrollHeight || 0);
                    return Math.max(...heights, 0);
                }""",
                container,
            ) or 0)
        except Exception:  # noqa: BLE001 — progress is a hint, not a step
            return 0

    async def _links_in_open_dialog(self, page, scroll_rounds: int,
                                    wanted: int = 0) -> list[str]:
        """Read and scroll a dialog that is already open, to the end of it.

        The list loads a page at a time when scrolled to the bottom, and
        that fetch is sometimes slow. Everything here is about telling a
        slow fetch apart from a finished list, because getting that wrong
        in either direction is what made repeat runs return a different
        number every time: 525, then 92, on the same account.

        So progress means *either* new names or a taller list, and running
        out of patience takes several quiet rounds with a growing pause
        between them — not four fixed ones.
        """
        selectors = self.SELECTORS.get("liker") or ()
        if not selectors:
            return []
        await self._first_visible(page, tuple(selectors), timeout_ms=COMPOSER_MS)
        await page.wait_for_timeout(SETTLE_MS)

        seen: dict[str, None] = {}

        async def harvest() -> int:
            for name in await self._collect_profile_links(page, selectors):
                seen.setdefault(name)
            return len(seen)

        await harvest()
        height = await self._dialog_height(page)
        deadline = time.monotonic() + (DIALOG_BUDGET_MS / 1000)

        quiet = 0
        for _ in range(max(scroll_rounds, 0)):
            if wanted and len(seen) >= wanted:
                break
            if time.monotonic() > deadline:
                print(f"[discovery] stopped after {DIALOG_BUDGET_MS // 1000}s on "
                      f"one list, with {len(seen)} name(s)", flush=True)
                break

            names_before, height_before = len(seen), height
            await self._load_more(page)
            await page.wait_for_timeout(SCROLL_PAUSE_MS)
            await harvest()
            height = await self._dialog_height(page)

            if len(seen) > names_before or height > height_before:
                quiet = 0
                continue

            # Nothing yet. Wait longer each time before deciding the list
            # has ended — a slow page is not a finished one.
            quiet += 1
            if quiet >= DIALOG_QUIET_ROUNDS:
                break
            await page.wait_for_timeout(SCROLL_PAUSE_MS * quiet)
            await harvest()
            height = await self._dialog_height(page)
            if len(seen) > names_before or height > height_before:
                quiet = 0
        return list(seen)

    async def _profile_links(self, page, url: str, selectors,
                             scroll_rounds: int = 0) -> list[str]:
        """Profile handles linked from a page, in order, deduped.

        Scrolls up to `scroll_rounds` times, stopping early the moment a
        round adds nobody — a post with nine comments should not sit through
        ten scrolls to prove it.
        """
        if not selectors:
            return []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            await self._dismiss_overlays(page)
            # Wait for the list itself rather than a fixed pause. The likes
            # dialog arrives after its URL does, and reading too early
            # returns nobody at all — which reads as "this post has no
            # likes" rather than "ask again in a moment".
            await self._first_visible(page, tuple(selectors), timeout_ms=COMPOSER_MS)
            await page.wait_for_timeout(SETTLE_MS)

            names = await self._collect_profile_links(page, selectors)
            for _ in range(max(scroll_rounds, 0)):
                await self._load_more(page)
                grown = await self._collect_profile_links(page, selectors)
                if grown and len(grown) <= len(names):
                    # Stop only once there is something and it stopped
                    # growing. Breaking on "no growth" alone gave up on an
                    # empty list, and a dialog that has not finished opening
                    # is empty — a followers list read that way came back
                    # with nobody, which reads as an account with no
                    # followers rather than one still loading.
                    break
                names = grown
            return names
        except Exception as exc:  # noqa: BLE001
            print(f"[discovery] {url} failed: {type(exc).__name__}: {exc}", flush=True)
            return []

    def _absolute(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return f"{self.SITE_URL.rstrip('/')}/{href.lstrip('/')}"

    def hashtag_url(self, tag: str) -> str:
        raise DiscoveryUnsupported(f"{self.PLATFORM} has no hashtag URL template.")

    def username_from_url(self, href: str) -> str:
        """The profile handle in this URL, or "" if it is not a profile."""
        return ""

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
