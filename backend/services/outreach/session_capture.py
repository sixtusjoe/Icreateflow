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
worth withholding rather than merely documenting. So it is off unless
`ICREATE_OUTREACH_BROWSER_LOGIN` is set, and the API reports it as
unavailable rather than failing obscurely.

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
from services.outreach.constants import ACCOUNT_IDLE
from services.outreach.crypto import crypto_available, encrypt_session

#: Where to send the operator to sign in, and the cookie that proves they did.
PLATFORMS: dict[str, dict[str, str]] = {
    "tiktok": {
        "login_url": "https://www.tiktok.com/login",
        "cookie": "sessionid",
        "domain": "tiktok.com",
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
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("ICREATE_LOGIN_TIMEOUT", "600"))

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
    return (os.environ.get("ICREATE_OUTREACH_BROWSER_LOGIN") or "").strip().lower() not in (
        "", "0", "false", "no", "off",
    )


def unavailable_reason() -> Optional[str]:
    """Why a browser sign-in cannot be offered here, or None if it can."""
    if not is_enabled():
        return (
            "Browser sign-in is switched off on this host. It opens a real "
            "window, so it is only enabled where someone can see it — set "
            "ICREATE_OUTREACH_BROWSER_LOGIN=1 when running the app locally."
        )
    if not crypto_available():
        return (
            "No encryption key, so a captured session could not be stored. "
            "Set ICREATE_OUTREACH_SECRET (or ICREATE_JWT_SECRET)."
        )
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return "Playwright is not installed on this host."
    return None


def status_for(account_id: int) -> Optional[Capture]:
    return _CAPTURES.get(int(account_id))


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

    state = None
    try:
        from playwright.async_api import async_playwright

        # Headed is the whole point — a person has to sign in. The override
        # exists so this can be exercised without a display.
        headless = os.environ.get("ICREATE_LOGIN_HEADLESS", "0") not in ("0", "false", "")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 860}, locale="en-US"
            )
            page = await context.new_page()
            await page.goto(spec["login_url"], wait_until="domcontentloaded")

            capture.status = STATUS_WAITING
            capture.message = (
                f"A browser window is open at {capture.platform}. Sign in as "
                f"“{name}” — this closes and saves by itself once you are in."
            )

            waited = 0
            while waited < timeout_seconds:
                if not browser.is_connected():
                    finish(STATUS_FAILED, "The window was closed before sign-in finished.")
                    return
                try:
                    cookies = await context.cookies()
                except Exception:  # noqa: BLE001 — context torn down under us
                    finish(STATUS_FAILED, "The window was closed before sign-in finished.")
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
    except Exception as exc:  # noqa: BLE001 — the UI has to hear about it
        finish(STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:300])
        return

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
