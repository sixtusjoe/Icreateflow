#!/usr/bin/env python
"""Check X's selector table against the real site, with a signed-in account.

Everything past X's login wall is a hypothesis until this runs. Logged out,
x.com serves nothing — a profile comes back with an empty body — so the
table was built from X's own `data-testid` attributes rather than from
anything anyone has seen.

That is precisely how Instagram shipped a Follow selector matching nothing
at all, for a hundred targets, while the log said the profiles simply did
not accept messages. This is the hour that would have saved.

    python scripts/verify_x_selectors.py --account <id> --target <handle>

Reads. Never sends, never follows, never clicks anything that changes
state — it opens two profiles and reports which selectors resolve.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

import database as db  # noqa: E402
from services.outreach.crypto import decrypt_session  # noqa: E402
from services.outreach.browser.playwright_x import PlaywrightXMessenger  # noqa: E402

#: What has to resolve on a profile you can message, and what must not.
ON_A_SENDABLE_PROFILE = {
    "profile_loaded": True,
    "message_button": True,
    "follow_button": None,      # depends on whether you already follow
    "already_following": None,
    "follow_requested": False,
    "profile_missing": False,
    "login_wall": False,
    "site_error": False,
}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, required=True,
                        help="a sending account with a stored X session")
    parser.add_argument("--target", default="nasa",
                        help="a public handle that accepts DMs")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    await db.init_db()
    database = await db.get_db()
    try:
        row = (await database.session.execute(
            text("SELECT name, platform, session_state_encrypted "
                 "  FROM outreach_sending_accounts WHERE id = :i"),
            {"i": args.account},
        )).mappings().first()
    finally:
        await database.close()

    if not row:
        print(f"No sending account {args.account}.")
        return 2
    if row["platform"] != "x":
        print(f"Account {args.account} is {row['platform']!r}, not x.")
        return 2
    if not row["session_state_encrypted"]:
        print(f"Account {args.account} ({row['name']}) has no stored session — "
              f"sign it in first.")
        return 2

    driver = PlaywrightXMessenger(headless=args.headless, timeout_ms=30000)
    await driver.startup()
    failures = 0
    try:
        acct = {"id": args.account, "name": row["name"], "platform": "x",
                "session_state": decrypt_session(row["session_state_encrypted"])}
        page = await (await driver._context_for(acct)).new_page()

        await page.goto(driver.profile_url(args.target),
                        wait_until="domcontentloaded", timeout=45000)
        await driver._dismiss_overlays(page)
        await page.wait_for_timeout(4000)

        if await driver._present(page, driver.SELECTORS["login_wall"]):
            print("Signed out — the stored session is not valid any more.")
            return 2

        print(f"\n@{args.target}\n" + "-" * 58)
        for key, expected in ON_A_SENDABLE_PROFILE.items():
            found = await driver._first_visible_tiered(
                page, driver.SELECTORS.get(key, ()), timeout_ms=2500
            ) is not None
            if expected is None:
                verdict = "either"
            elif found == expected:
                verdict = "ok"
            else:
                verdict, failures = "WRONG", failures + 1
            print(f"  {key:22} found={str(found):5} expected="
                  f"{str(expected):5} {verdict}")

        summary = await driver.profile_summary(page, args.target)
        print(f"\n  profile_summary -> {summary}")
        if not summary.get("followers"):
            print("  !! follower count did not parse — the header text moved")
            failures += 1

        print("\nNot checked here, because checking them changes something:")
        print("  message_input / send_button / sent_confirmation — open a DM")
        print("  follow_requested — needs a protected account")
        print("  recipient_refused / message_refused — need a real send")
    finally:
        await driver.shutdown()

    print(f"\n{failures} selector(s) wrong." if failures
          else "\nEvery selector checked resolved as expected.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
