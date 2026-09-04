#!/usr/bin/env python3
"""Capture an authorized browser session for an outreach sending account.

Opens a real browser window on the server's virtual display, waits for you
to sign in by hand, then encrypts the resulting session straight into the
account row.

The point of doing this on the server rather than on a laptop: the session
is created on the exact machine, IP and browser build that will later use
it. Signing in somewhere else and copying the cookies over means the
platform sees an established session jump to a new IP, which is the most
common reason a freshly-imported session gets challenged or logged out.

Nothing is written to disk — the storage state goes from the browser
straight into the encrypted column. Run it through
`deploy/outreach-login.sh`, which sets up the display and the VNC tunnel.

    python3 scripts/outreach_login.py --list
    python3 scripts/outreach_login.py 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402
from services.outreach.constants import ACCOUNT_IDLE  # noqa: E402
from services.outreach.crypto import crypto_available, encrypt_session  # noqa: E402

#: Where to send the operator to sign in, and the cookie that proves they did.
PLATFORMS = {
    "tiktok": {
        "login_url": "https://www.tiktok.com/login",
        "cookie": "sessionid",
        "domain": "tiktok.com",
    },
}

POLL_SECONDS = 2


async def list_accounts() -> int:
    database = await db.get_db()
    try:
        rows = await db.get_sending_accounts(database)
    finally:
        await database.close()

    if not rows:
        print("No sending accounts yet — add one in the app first "
              "(Outreach → Accounts).")
        return 1

    print(f"{'ID':>4}  {'PLATFORM':<10} {'SESSION':<10} {'STATUS':<8} NAME")
    for row in rows:
        item = dict(row)
        print(
            f"{item['id']:>4}  {item['platform']:<10} "
            f"{'stored' if item.get('session_state_encrypted') else '—':<10} "
            f"{item['status']:<8} {item['name']}"
        )
    return 0


async def capture(account_id: int, timeout_seconds: int) -> int:
    if not crypto_available():
        print("ERROR: no encryption key. Set ICREATE_OUTREACH_SECRET (or "
              "ICREATE_JWT_SECRET) before capturing a session.")
        return 1

    database = await db.get_db()
    try:
        row = await db.get_sending_account(database, account_id)
    finally:
        await database.close()
    if not row:
        print(f"ERROR: no sending account with id {account_id}. "
              f"Run with --list to see them.")
        return 1

    account = dict(row)
    spec = PLATFORMS.get(account["platform"])
    if not spec:
        print(f"ERROR: no login flow for platform {account['platform']!r}.")
        return 1

    from playwright.async_api import async_playwright

    # Headed is the whole point — a person has to sign in. The override
    # exists so the capture flow can be tested without a display.
    headless = os.environ.get("ICREATE_LOGIN_HEADLESS", "0") not in ("0", "false", "")

    print(f"==> Signing in as “{account['name']}” ({account['platform']})")
    if account.get("session_state_encrypted"):
        print("    This account already has a session — finishing the login "
              "will replace it.")

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

        print()
        print("    A browser window is open on the server's display.")
        print("    Connect over the VNC tunnel, sign in, and this will")
        print("    capture the session automatically — no copy-paste.")
        print(f"    Waiting up to {timeout_seconds // 60} minutes…")
        print()

        state = None
        waited = 0
        while waited < timeout_seconds:
            if not browser.is_connected():
                print("!!  Browser was closed before sign-in completed.")
                return 1
            try:
                cookies = await context.cookies()
            except Exception:  # noqa: BLE001 — context torn down under us
                print("!!  Browser was closed before sign-in completed.")
                return 1

            signed_in = any(
                c.get("name") == spec["cookie"]
                and (c.get("value") or "").strip()
                and spec["domain"] in (c.get("domain") or "")
                for c in cookies
            )
            if signed_in:
                # Let the post-login redirects settle so the capture includes
                # everything the site set on the way in.
                await asyncio.sleep(3)
                state = await context.storage_state()
                break

            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS

        await context.close()
        await browser.close()

    if state is None:
        print(f"!!  Timed out after {timeout_seconds}s without a completed "
              f"sign-in. Nothing was saved.")
        return 1

    database = await db.get_db()
    try:
        await db.update_sending_account(
            database,
            account_id,
            session_state_encrypted=encrypt_session(json.dumps(state)),
            session_reference=f"server-login/account-{account_id}",
            session_updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status=ACCOUNT_IDLE,
            paused_reason=None,
            consecutive_errors=0,
        )
        await db.log_outreach_audit(
            database, "account.session_set", "account", account_id,
            detail=f"captured on server, {len(state.get('cookies') or [])} cookie(s)",
        )
    finally:
        await database.close()

    print(f"==> Session stored for “{account['name']}” "
          f"({len(state.get('cookies') or [])} cookies, encrypted).")
    print("    The account is enabled and ready. Nothing was written to disk.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture a browser session for an outreach sending account."
    )
    parser.add_argument("account_id", nargs="?", type=int, help="Account to sign in.")
    parser.add_argument("--list", action="store_true", help="List sending accounts.")
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Seconds to wait for sign-in (default 600).",
    )
    args = parser.parse_args()

    from sqlalchemy.exc import SQLAlchemyError

    try:
        if args.list or args.account_id is None:
            return asyncio.run(list_accounts())
        return asyncio.run(capture(args.account_id, args.timeout))
    except (SQLAlchemyError, ConnectionRefusedError) as exc:
        # An operator running this doesn't need a sixty-line traceback to
        # learn that Postgres is down or the DSN is wrong. asyncpg raises
        # ConnectionRefusedError straight through the pool rather than
        # wrapping it, so both have to be caught.
        print(f"ERROR: cannot reach the database — {type(exc).__name__}.")
        print("       Check ICREATE_DB_DSN in /srv/icreateflow/backend/.env "
              "and that postgresql is running.")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled — nothing was saved.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
