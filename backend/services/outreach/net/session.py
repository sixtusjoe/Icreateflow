"""HTTP plumbing: cookies, proxy, retries. No platform knowledge.

If anything here ever needs to know which platform it is talking to, that
is the signal it has been written in the wrong file.

One deliberate omission: TLS impersonation. The measured reads all went
through plain `httpx` against real TikTok and were served normally, so
`curl_cffi` is not a dependency until something says it needs to be. It
would slot in behind this class without changing a caller.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

#: What the browser that mints the signatures reports. The two must agree:
#: a signature minted in Chrome and replayed under a different user agent
#: is a mismatch the platform can see for free.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def cookies_from_state(state: Any, domain_hint: str) -> dict[str, str]:
    """Pull a cookie jar out of a Playwright `storage_state`.

    Accepts the decrypted JSON string or the parsed dict, because callers
    have one or the other depending on how far up they sit.
    """
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            return {}
    if not isinstance(state, dict):
        return {}
    return {
        c["name"]: c["value"]
        for c in state.get("cookies", [])
        if domain_hint in (c.get("domain") or "") and c.get("name")
    }


class ReadSession:
    """One account's HTTP identity: its cookies, its proxy, its headers.

    Async because everything above it is: the drivers, discovery and the
    worker are all `async def`, and a minter that drives Playwright cannot
    be called from a synchronous loop without starting a second event loop
    inside the first.
    """

    def __init__(
        self,
        cookies: dict[str, str],
        *,
        headers: Optional[dict[str, str]] = None,
        proxy_url: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        self._cookies = dict(cookies or {})
        self._headers = {"user-agent": DEFAULT_USER_AGENT, "accept": "*/*",
                         "accept-language": "en-US,en;q=0.9"}
        self._headers.update(headers or {})
        self._proxy_url = proxy_url or None
        self._timeout = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "ReadSession":
        kwargs: dict[str, Any] = {
            "headers": self._headers,
            "cookies": self._cookies,
            "timeout": self._timeout,
        }
        if self._proxy_url:
            # Reads go out through the account's own address, for the same
            # reason sends do: several accounts sharing one IP is the most
            # obvious thing about them.
            kwargs["proxy"] = self._proxy_url
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    def replace_headers(self, headers: dict[str, str]) -> None:
        """Adopt a freshly minted request's headers mid-read.

        A signature expires in minutes, so a long read re-mints and carries
        on. The cookie jar is left alone: it belongs to the account, not to
        the signature.
        """
        if self._client is None:
            return
        for key, value in (headers or {}).items():
            self._client.headers[key] = value

    async def get(self, url: str) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("ReadSession used outside its context manager")
        return await self._client.get(url)
