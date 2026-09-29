"""Minting a signed request. The only place a browser appears.

TikTok's `X-Gnarly` / `X-Dynosaur` come out of its own obfuscated JS, and
nothing hand-built substitutes for them: measured 2026-09-22, a request
with the signing parameters stripped was served **zero** pages, across
three variants, against an unthrottled account. So this is not
"browserless" and is not called that — it is DOM-less. A browser opens,
produces one signed request, and closes; the reading is plain HTTP.

Two measured details decide the shape:

* **Headless works.** Headless and headed mint an identical signature and
  read the same comments, so nothing needs to appear on anyone's screen.
* **A signature outlives the browser.** It does not cover `cursor`, so one
  mint pages until it expires, which took 35 and 16 requests in two
  observed runs. That is why minting is a separate step rather than
  something the reader does per request.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from services.outreach.net.session import DEFAULT_USER_AGENT
from services.outreach.net.tiktok import endpoints
from services.outreach.net.tiktok.comments import Minted

#: Copied from the working driver rather than invented. A bare Chromium is
#: served TikTok's "Site Maintenance" page and makes no API calls at all.
CHROMIUM_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-features=WebBluetooth",
)

#: The page hydrates late: its `[data-e2e]` count climbs 3 -> 20 -> 175 over
#: roughly fifteen seconds, and a click at seven seconds finds nothing.
TAB_TIMEOUT_MS = 45_000
REQUEST_TIMEOUT_S = 30


class MintUnavailable(RuntimeError):
    """No signature could be obtained — Playwright missing, or the page
    never made the call."""


class TikTokSigner:
    """Holds one browser context and mints from it on demand.

    The context is kept open between mints because opening one is most of
    the cost, and a read needs several.
    """

    def __init__(self, session_state: Any, *, headless: bool = True,
                 post_url: Optional[str] = None):
        self._state = (json.loads(session_state)
                       if isinstance(session_state, str) else session_state)
        self._headless = headless
        self._post_url = post_url
        self._pw = None
        self._browser = None
        self._context = None
        self.mints = 0

    async def __aenter__(self) -> "TikTokSigner":
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - deployment shape
            raise MintUnavailable(
                "Playwright is not installed on this host, so no signature "
                "can be minted. The reader cannot run here."
            ) from exc
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless, args=list(CHROMIUM_ARGS))
        self._context = await self._browser.new_context(
            storage_state=self._state, user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 900}, locale="en-US")
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for close in (getattr(self._context, "close", None),
                      getattr(self._browser, "close", None),
                      getattr(self._pw, "stop", None)):
            if close is None:
                continue
            try:
                await close()
            except Exception:  # noqa: BLE001 — teardown must not raise
                pass

    def minter(self, post_url: str):
        """A `mint` callable bound to one post, for `read_commenters`."""
        async def _mint() -> Minted:
            return await self.mint(post_url)
        return _mint

    async def mint(self, post_url: str) -> Minted:
        """Open the post and take the comment request the page makes."""
        if self._context is None:
            raise MintUnavailable("TikTokSigner used outside its context manager")
        page = await self._context.new_page()
        captured: asyncio.Future = asyncio.get_event_loop().create_future()

        def on_request(request) -> None:
            if (endpoints.COMMENT_LIST.split("tiktok.com")[-1] in request.url
                    and "reply" not in request.url and not captured.done()):
                captured.set_result({"url": request.url,
                                     "headers": dict(request.headers)})

        page.on("request", on_request)
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=60_000)
            # The right-hand panel opens on "You may like", not "Comments",
            # so without this the page requests related videos and never
            # the comment list. The tab's class is a rotating hash, so it is
            # matched by role and text.
            try:
                tab = page.get_by_role("button", name="Comments").first
                await tab.wait_for(state="visible", timeout=TAB_TIMEOUT_MS)
                await tab.click()
            except Exception:  # noqa: BLE001 — the scroll below can still do it
                pass
            # Clicking a tab that is already selected fires no request, so
            # the panel is scrolled until the page asks for comments itself
            # rather than trusting the click.
            for _ in range(12):
                if captured.done():
                    break
                await page.mouse.move(1060, 450)
                await page.mouse.wheel(0, 900)
                await page.wait_for_timeout(1200)
            payload = await asyncio.wait_for(captured, timeout=REQUEST_TIMEOUT_S)
            cookies = {c["name"]: c["value"] for c in await self._context.cookies()
                       if "tiktok" in (c.get("domain") or "")}
        except asyncio.TimeoutError as exc:
            raise MintUnavailable(
                f"The page never requested its comment list for {post_url}"
            ) from exc
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

        self.mints += 1
        return Minted(payload["url"], payload["headers"], cookies)
