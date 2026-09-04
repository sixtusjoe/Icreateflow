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
from typing import Any, Optional

from services.outreach.browser import MessageResult
from services.outreach.constants import (
    RESULT_BROWSER_ERROR,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SESSION_EXPIRED,
    RESULT_UNEXPECTED_PAGE,
)

#: Ordered fallbacks — the first selector that resolves wins.
SELECTORS: dict[str, tuple[str, ...]] = {
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
    "message_button": (
        "[data-e2e='message-button']",
        "button:has-text('Message')",
        "a:has-text('Message')",
    ),
    "message_input": (
        "[data-e2e='message-input-area']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
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
}

DEFAULT_TIMEOUT_MS = int(os.environ.get("ICREATE_OUTREACH_TIMEOUT_MS", "30000"))
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

            if await self._present(page, SELECTORS["profile_missing"]):
                return MessageResult.failure(
                    RESULT_PROFILE_UNAVAILABLE,
                    "Profile not found or private",
                    url=url,
                )
            if await self._present(page, SELECTORS["login_wall"]):
                # The stored session no longer authenticates us.
                return MessageResult.failure(
                    RESULT_SESSION_EXPIRED,
                    "Session expired — TikTok is showing the login wall",
                    url=url,
                )
            if await self._present(page, SELECTORS["rate_limited"]):
                return MessageResult.failure(
                    RESULT_RATE_LIMITED, "Platform is rate limiting this account", url=url
                )

            # 3-4. Is the messaging interface available, and open it.
            message_button = await self._first_visible(page, SELECTORS["message_button"])
            if message_button is None:
                return MessageResult.failure(
                    RESULT_MESSAGING_UNAVAILABLE,
                    "No Message button on this profile — the account does not accept DMs",
                    url=url,
                )
            await message_button.click()

            editor = await self._first_visible(page, SELECTORS["message_input"], timeout_ms=8000)
            if editor is None:
                if await self._present(page, SELECTORS["login_wall"]):
                    return MessageResult.failure(
                        RESULT_SESSION_EXPIRED, "Session expired at the message step", url=url
                    )
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    "Message composer did not open — the page structure may have changed",
                    url=page.url,
                )

            # 5. Enter the message. `type` rather than `fill` — the composer
            # is a contenteditable that ignores programmatic value sets.
            await editor.click()
            await editor.type(message, delay=25)

            # 6. Submit.
            send_button = await self._first_visible(page, SELECTORS["send_button"], timeout_ms=4000)
            if send_button is not None:
                await send_button.click()
            else:
                await page.keyboard.press("Enter")

            # 7. Verify: the composer empties and the message appears in the
            # thread. Neither is guaranteed by TikTok, so a miss is reported
            # as unexpected_page rather than assumed successful.
            await page.wait_for_timeout(1500)
            if await self._present(page, SELECTORS["rate_limited"]):
                return MessageResult.failure(
                    RESULT_RATE_LIMITED, "Rate limited while sending", url=page.url
                )

            confirmed = False
            try:
                body = (await page.locator("body").inner_text(timeout=3000)) or ""
                confirmed = message[:60] in body
            except Exception:  # noqa: BLE001
                confirmed = False
            if not confirmed:
                confirmed = await self._present(page, SELECTORS["sent_confirmation"])
            if not confirmed:
                return MessageResult.failure(
                    RESULT_UNEXPECTED_PAGE,
                    "Could not confirm the message was delivered",
                    url=page.url,
                )

            return MessageResult.sent(url=page.url)

        except Exception as exc:  # noqa: BLE001 — every browser fault is a result
            name = type(exc).__name__
            status = (
                RESULT_NAVIGATION_TIMEOUT if "Timeout" in name else RESULT_BROWSER_ERROR
            )
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
