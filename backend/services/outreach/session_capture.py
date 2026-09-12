"""Capture an authorized browser session by opening a real login window.

The operator signs in by hand; nothing here ever sees a password. A browser
opens on whatever machine runs this process, waits for the platform's
session cookie to appear, and writes the resulting storage state — encrypted
— straight into the account row. Nothing touches disk.

This is the same flow `scripts/outreach_login.py` has always run from a
terminal. It lives here so the app can offer it as a button, and so both
callers share one implementation rather than drifting apart.

WHERE IT CAN RUN
----------------
Opening a window only makes sense where a person can see it: a laptop
running the backend locally. On a headless server there is no display, and
an endpoint that launches browsers on a production host is a capability
worth withholding rather than merely documenting. The gate is shared with
watched sends — see `local_browser`.

The work outlives the request that starts it — signing in takes minutes —
so a capture runs as a background task and the caller polls for its state.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import database as db
from services.outreach import display_pool, local_browser, proxies
from services.outreach.browser.playwright_base import CHROMIUM_ARGS
from services.outreach.constants import ACCOUNT_IDLE
from services.outreach.crypto import (
    crypto_available,
    decrypt_session,
    encrypt_session,
)

#: Where to send the operator to sign in, and the cookie that proves they did.
PLATFORMS: dict[str, dict[str, str]] = {
    "tiktok": {
        "login_url": "https://www.tiktok.com/login",
        "cookie": "sessionid",
        "domain": "tiktok.com",
    },
    "x": {
        # Verified: logged out, every x.com URL redirects into this flow.
        "login_url": "https://x.com/i/flow/login",
        # X's session cookie. `ct0` is the CSRF token and is set before
        # sign-in, so it proves nothing; this one only appears once
        # authenticated.
        "cookie": "auth_token",
        "domain": "x.com",
    },
    "instagram": {
        "login_url": "https://www.instagram.com/accounts/login/",
        # Instagram's session cookie. `csrftoken` is set before sign-in, so
        # it proves nothing; this one only appears once authenticated.
        "cookie": "sessionid",
        "domain": "instagram.com",
    },
}

POLL_SECONDS = 2
#: Consecutive failed cookie reads tolerated before calling the window gone.
#: The read races navigation, and signing in is all navigation.
COOKIE_BLIPS_ALLOWED = 3
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("ICREATE_LOGIN_TIMEOUT", "600"))

#: How many times to ask for the login page before giving up.
#:
#: A datacenter IP requesting a login page is precisely the traffic these
#: platforms throttle, and the refusal is a transient 4xx — Chromium
#: surfaces it as `net::ERR_HTTP_RESPONSE_CODE_FAILURE`, which reads like a
#: broken app rather than "come back in a minute". One bad response used to
#: end a sign-in the operator was waiting on, so ask again.
GOTO_ATTEMPTS = 3
#: Waits between those attempts; there is one fewer wait than attempt.
GOTO_BACKOFF_SECONDS = (2, 5)


class LoginUnreachable(Exception):
    """The platform would not serve its login page."""


def context_options(proxy: Optional[proxies.Proxy]) -> dict[str, Any]:
    """Everything the sign-in window's context needs, the proxy included.

    Shared with the tests so that what they exercise is what runs: an
    options dict assembled twice is an options dict that can lose its
    proxy in one of the two places.
    """
    options: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 860},
        "locale": "en-US",
    }
    if proxy is not None:
        options["proxy"] = proxy.playwright()
    return options


async def open_login_page(page: Any, url: str, label: str) -> None:
    """Navigate to a login page, tolerating a refusal or two.

    Both callers that open a sign-in window come through here, so the
    retry — and the log line that makes a failure diagnosable afterwards —
    cannot drift between them.
    """
    last: Optional[BaseException] = None
    trouble = ""
    for attempt in range(1, GOTO_ATTEMPTS + 1):
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            # A refusal arrives in one of two shapes and both have to be
            # caught. Chromium raises ERR_HTTP_RESPONSE_CODE_FAILURE for
            # some error responses, but hands others back as an ordinary
            # response carrying a 4xx/5xx and an empty body — a blank
            # window the operator would sit in front of, waiting to sign
            # in to a page that never arrived.
            status = response.status if response is not None else 0
            if status >= 400:
                trouble = f"HTTP {status}"
                raise LoginUnreachable(f"{url} answered {status}")
            if attempt > 1:
                print(
                    f"[outreach] sign-in for {label}: {url} opened on attempt "
                    f"{attempt} of {GOTO_ATTEMPTS}",
                    flush=True,
                )
            return
        except LoginUnreachable as exc:
            last = exc
            print(
                f"[outreach] sign-in for {label}: {url} refused on attempt "
                f"{attempt} of {GOTO_ATTEMPTS} — {trouble}",
                flush=True,
            )
            if attempt < GOTO_ATTEMPTS:
                await asyncio.sleep(GOTO_BACKOFF_SECONDS[attempt - 1])
            continue
        except Exception as exc:  # noqa: BLE001 — reported below either way
            last = exc
            # Logged per attempt: the old code swallowed this entirely, so a
            # failure the operator saw on their phone left no trace on the
            # server at all.
            print(
                f"[outreach] sign-in for {label}: {url} refused on attempt "
                f"{attempt} of {GOTO_ATTEMPTS} — {type(exc).__name__}: "
                f"{str(exc).splitlines()[0][:160]}",
                flush=True,
            )
            if attempt < GOTO_ATTEMPTS:
                await asyncio.sleep(GOTO_BACKOFF_SECONDS[attempt - 1])
    raise LoginUnreachable(
        f"{label} would not open its sign-in page after {GOTO_ATTEMPTS} "
        f"tries — the site refused the request from this server. That is "
        f"usually temporary; try again in a minute."
    ) from last

# --- states the caller can see -------------------------------------------
STATUS_OPENING = "opening"
STATUS_WAITING = "waiting"
STATUS_SAVED = "saved"
STATUS_FAILED = "failed"


@dataclass
class Capture:
    """One sign-in attempt, as the UI needs to see it."""

    account_id: int
    platform: str
    status: str = STATUS_OPENING
    message: str = "Opening a browser window…"
    cookies: int = 0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str] = None
    #: The VNC port of this capture's own screen, when it has one. A shared
    #: display showed every session to anyone holding any ticket.
    vnc_port: Optional[int] = None

    @property
    def done(self) -> bool:
        return self.status in (STATUS_SAVED, STATUS_FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "status": self.status,
            "message": self.message,
            "cookies": self.cookies,
            "done": self.done,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


#: In-flight and recently finished captures, by account. Deliberately in
#: memory: a half-finished sign-in means nothing after a restart, since the
#: browser window died with the process.
_CAPTURES: dict[int, Capture] = {}
_TASKS: dict[int, asyncio.Task] = {}


def is_enabled() -> bool:
    """Is opening a login window allowed on this host?"""
    return local_browser.is_enabled()


def unavailable_reason() -> Optional[str]:
    """Why a browser sign-in cannot be offered here, or None if it can."""
    reason = local_browser.unavailable_reason("Browser sign-in")
    if reason:
        return reason
    if not crypto_available():
        return (
            "No encryption key, so a captured session could not be stored. "
            "Set ICREATE_OUTREACH_SECRET (or ICREATE_JWT_SECRET)."
        )
    return None


def status_for(account_id: int) -> Optional[Capture]:
    return _CAPTURES.get(int(account_id))


def running_accounts() -> list[int]:
    """Accounts with a sign-in window open right now.

    Shutting the API down closes those windows — the capture is a task in
    this process, and its browser goes with it. Whoever is stopping the
    process needs to be able to find that out before doing it, because on
    the other side of it is a person halfway through typing a password.
    """
    return [
        account_id for account_id, task in _TASKS.items()
        if task is not None and not task.done()
    ]


def any_running() -> bool:
    return bool(running_accounts())


def is_running(account_id: int) -> bool:
    task = _TASKS.get(int(account_id))
    return task is not None and not task.done()


def start(account: dict[str, Any], timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> Capture:
    """Open a login window for this account and return immediately.

    Raises ValueError when the platform has no login flow, or a capture is
    already running for this account — two windows for one account would
    race each other into the same row.
    """
    account_id = int(account["id"])
    platform = (account.get("platform") or "").lower()
    if platform not in PLATFORMS:
        raise ValueError(f"No login flow for platform {platform!r}.")
    if is_running(account_id):
        raise ValueError("A sign-in window is already open for this account.")

    capture = Capture(account_id=account_id, platform=platform)
    _CAPTURES[account_id] = capture
    _TASKS[account_id] = asyncio.create_task(
        _run(account, capture, timeout_seconds)
    )
    return capture


async def _run(account: dict[str, Any], capture: Capture, timeout_seconds: int) -> None:
    """Drive the window, then store what it produced."""
    account_id = int(account["id"])
    spec = PLATFORMS[capture.platform]
    name = account.get("name") or f"account {account_id}"

    def finish(status: str, message: str, cookies: int = 0) -> None:
        capture.status = status
        capture.message = message
        capture.cookies = cookies
        capture.finished_at = datetime.now(timezone.utc).isoformat()

    # A session has to be created from the address it will later send
    # from. Minted on the server's own IP and then used through a
    # residential proxy, it is an established session that jumps country
    # on its first use — which is the single most common reason a fresh
    # session gets challenged. See scripts/outreach_login.py.
    #
    # A proxy that is set but unusable therefore fails the sign-in rather
    # than quietly falling back to the server's address: the fallback
    # produces a session that looks fine here and is challenged later,
    # which is the harder failure to trace.
    try:
        proxy_url = decrypt_session(account.get("proxy_url_encrypted"))
    except Exception as exc:  # noqa: BLE001 — narrow scope, reported as-is
        # Unreadable ciphertext raised out of this task before, which left
        # the capture sitting on "opening" for ever with nothing to show.
        print(
            f"[outreach] sign-in for {name}: stored proxy could not be "
            f"decrypted — {type(exc).__name__}: {exc}",
            flush=True,
        )
        finish(
            STATUS_FAILED,
            f"This account's stored proxy could not be read "
            f"({type(exc).__name__}). Set it again on the account.",
        )
        return

    try:
        proxy = proxies.parse(proxy_url)
    except proxies.ProxyInvalid as exc:
        finish(STATUS_FAILED, f"This account's proxy cannot be used: {exc}")
        return

    state = None
    screen = None
    try:
        from playwright.async_api import async_playwright

        # Headed is the whole point — a person has to sign in. The override
        # exists so this can be exercised without a display.
        headless = os.environ.get("ICREATE_LOGIN_HEADLESS", "0") not in ("0", "false", "")

        # A screen of this session's own, where the host can give one. The
        # alternative is every visible browser sharing one display, which
        # x11vnc streams whole — so two people signing in at once would
        # watch each other type.
        screen = None if headless else await display_pool.acquire()
        if screen is not None:
            capture.vnc_port = screen.vnc_port
        async with async_playwright() as p:
            # Same flags as the sender, from one list — the Bluetooth one in
            # particular is a crash fix, and this is the window it was
            # crashing. See CHROMIUM_ARGS.
            browser = await p.chromium.launch(
                headless=headless, args=list(CHROMIUM_ARGS),
                env={**os.environ, **(screen.env if screen else {})},
            )
            context = await browser.new_context(**context_options(proxy))
            page = await context.new_page()
            await open_login_page(page, spec["login_url"], capture.platform)

            capture.status = STATUS_WAITING
            capture.message = (
                f"A browser window is open at {capture.platform}. Sign in as "
                f"“{name}” — this closes and saves by itself once you are in."
            )

            waited = 0
            blips = 0
            print(
                f"[outreach] sign-in window open for {name} ({capture.platform}) "
                f"via {proxy.safe if proxy else 'this server’s own address'} "
                f"— waiting up to {timeout_seconds // 60} minutes",
                flush=True,
            )
            while waited < timeout_seconds:
                if not browser.is_connected():
                    print(
                        f"[outreach] sign-in window for {name} disconnected after "
                        f"{waited}s — the browser process is gone",
                        flush=True,
                    )
                    finish(
                        STATUS_FAILED,
                        f"The sign-in window closed after {waited}s, before "
                        f"sign-in finished.",
                    )
                    return
                try:
                    cookies = await context.cookies()
                    blips = 0
                except Exception as exc:  # noqa: BLE001 — see below
                    # One failed read is not a closed window. The call goes
                    # over a pipe to the browser process and can lose a race
                    # with a navigation — and signing in is nothing but
                    # navigations. Giving up on the first one ends the
                    # sign-in under someone who is still typing.
                    blips += 1
                    if blips <= COOKIE_BLIPS_ALLOWED and browser.is_connected():
                        print(
                            f"[outreach] sign-in window for {name}: cookie read "
                            f"{blips} of {COOKIE_BLIPS_ALLOWED} failed "
                            f"({type(exc).__name__}) — still connected, retrying",
                            flush=True,
                        )
                        await asyncio.sleep(POLL_SECONDS)
                        waited += POLL_SECONDS
                        continue
                    # This used to report "the window was closed" for any
                    # failure at all, which is a guess dressed as a fact: a
                    # window that died on its own and one the operator shut
                    # produced the same sentence, and the actual exception
                    # was thrown away. Debugging it meant reproducing it.
                    print(
                        f"[outreach] sign-in window for {name} failed after "
                        f"{waited}s: {type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    finish(
                        STATUS_FAILED,
                        f"The sign-in window stopped responding after {waited}s "
                        f"({type(exc).__name__}). Nothing was saved.",
                    )
                    return

                if any(
                    c.get("name") == spec["cookie"]
                    and (c.get("value") or "").strip()
                    and spec["domain"] in (c.get("domain") or "")
                    for c in cookies
                ):
                    # Let the post-login redirects settle, so the capture
                    # includes everything the site set on the way in.
                    await asyncio.sleep(3)
                    state = await context.storage_state()
                    break

                await asyncio.sleep(POLL_SECONDS)
                waited += POLL_SECONDS

            await context.close()
            await browser.close()
    except asyncio.CancelledError:
        finish(STATUS_FAILED, "Sign-in was cancelled.")
        raise
    except LoginUnreachable as exc:
        # Already logged per attempt by open_login_page; the operator gets
        # the sentence, not Chromium's error code. A proxy in the path is
        # the likelier culprit than the site, and saying so beats sending
        # someone to look at the wrong thing.
        note = (
            f" The account's proxy ({proxy.safe}) is in the path — test it "
            f"from the account's settings."
            if proxy is not None
            else ""
        )
        finish(STATUS_FAILED, (str(exc) + note)[:300])
        return
    except Exception as exc:  # noqa: BLE001 — the UI has to hear about it
        # This used to be the one path that told the UI something and the
        # server nothing, which made a reported failure unreproducible.
        print(
            f"[outreach] sign-in window for {name} ({capture.platform}) "
            f"failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        finish(STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:300])
        return
    finally:
        # Hand the screen back on every exit — success, timeout, failure and
        # cancellation alike. A leaked Xvfb keeps a display number and a
        # port for the life of the process.
        await display_pool.release(screen)

    if state is None:
        finish(
            STATUS_FAILED,
            f"Timed out after {timeout_seconds // 60} minutes without a "
            f"completed sign-in. Nothing was saved.",
        )
        return

    database = await db.get_db()
    try:
        await db.update_sending_account(
            database,
            account_id,
            session_state_encrypted=encrypt_session(json.dumps(state)),
            session_reference=f"browser-login/account-{account_id}",
            session_updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status=ACCOUNT_IDLE,
            paused_reason=None,
            consecutive_errors=0,
        )
        await db.log_outreach_audit(
            database, "account.session_set", "account", account_id,
            detail=(
                f"captured in a browser window, "
                f"{len(state.get('cookies') or [])} cookie(s)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        finish(STATUS_FAILED, f"Signed in, but storing the session failed: {exc}"[:300])
        return
    finally:
        await database.close()

    finish(
        STATUS_SAVED,
        f"Signed in and stored — {len(state.get('cookies') or [])} cookies, encrypted.",
        cookies=len(state.get("cookies") or []),
    )
