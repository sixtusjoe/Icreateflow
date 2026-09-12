"""An outbound proxy per sending account.

Four accounts working one platform from one server share one IP, and that
is the single most obvious thing about them. A residential proxy each is
what makes them look like four people rather than one machine.

Playwright wants the credentials apart from the host, so a URL of the usual
`scheme://user:pass@host:port` shape is split here rather than handed over
whole — passed whole, the credentials are silently ignored and every
request goes out unauthenticated, which the proxy answers with 407 and the
driver reports as a page that would not load.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import unquote, urlsplit

#: Schemes a browser can actually use. SOCKS5 has no credential support in
#: Chromium, so a socks5 URL with a password in it cannot work and should
#: be refused rather than half-accepted.
SCHEMES = ("http", "https", "socks5")


class ProxyInvalid(ValueError):
    """The proxy URL cannot be used as written."""


@dataclass(frozen=True)
class Proxy:
    server: str
    username: Optional[str] = None
    password: Optional[str] = None

    def playwright(self) -> dict[str, Any]:
        out: dict[str, Any] = {"server": self.server}
        if self.username:
            out["username"] = self.username
        if self.password:
            out["password"] = self.password
        return out

    @property
    def safe(self) -> str:
        """The proxy without its password, for logs and for the UI."""
        if not self.username:
            return self.server
        scheme, _, rest = self.server.partition("://")
        return f"{scheme}://{self.username}@{rest}"


def parse(url: Optional[str]) -> Optional[Proxy]:
    """Split a proxy URL into what Playwright needs, or raise.

    None and blank mean "no proxy", which is not an error: it is how an
    account goes back to the server's own address.
    """
    if url is None or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in SCHEMES:
        raise ProxyInvalid(
            f"Proxy scheme must be one of {', '.join(SCHEMES)} — got "
            f"{parts.scheme or 'nothing'!r}")
    if not parts.hostname:
        raise ProxyInvalid("Proxy URL has no host")
    if parts.scheme == "socks5" and (parts.username or parts.password):
        raise ProxyInvalid(
            "Chromium cannot send a username and password to a SOCKS5 "
            "proxy. Use an http proxy, or one that authorises this "
            "server's IP instead")
    port = f":{parts.port}" if parts.port else ""
    return Proxy(
        server=f"{parts.scheme}://{parts.hostname}{port}",
        # Credentials are percent-encoded in a URL, and proxy passwords are
        # full of characters that have to be.
        username=unquote(parts.username) if parts.username else None,
        password=unquote(parts.password) if parts.password else None,
    )


async def egress_ip(proxy: Optional["Proxy"], timeout_ms: int = 25000) -> str:
    """The address the world sees when this proxy is used.

    Opens a real browser context through it and asks. Anything cheaper —
    checking the host resolves, opening a socket — proves the proxy exists,
    not that a page loads through it, and a proxy that accepts connections
    and then refuses to forward is a common enough way to waste a day.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                **({"proxy": proxy.playwright()} if proxy else {})
            )
            page = await context.new_page()
            # Plain text, one line, no JSON to parse or markup to change.
            await page.goto("https://api.ipify.org", wait_until="domcontentloaded",
                            timeout=timeout_ms)
            return ((await page.inner_text("body")) or "").strip()[:64]
        finally:
            await browser.close()
