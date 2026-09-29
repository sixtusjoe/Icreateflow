"""Deleting a person always wins.

`outreach_campaigns.user_id`, `outreach_sending_accounts.user_id` and four
more besides are foreign keys to `users.id` with no ON DELETE rule. Before
this, an account that had ever run a campaign could not be deleted at all:
Postgres refused the row, the endpoint raised, and the admin got a 500 with
nothing said. "You cannot remove this person because they have a campaign"
is not a policy anyone chose — it was a schema detail nobody had tested.

These tests hold the endpoint to the rule instead: a campaign, running or
not, is a line on the confirm dialog and never a veto.
"""
from __future__ import annotations

import pytest

import database as db
import main
from services.auth import hash_password
from services.outreach.constants import CAMPAIGN_RUNNING


async def _make_user(database, email="delete-me@example.com"):
    existing = await db.get_user_by_email(database, email)
    if existing:
        return dict(existing)["id"]
    return await db.create_user(database, email, hash_password("x" * 12), "Delete Me")


async def _count(database, sql, args):
    cur = await database.execute(sql, args)
    row = await cur.fetchone()
    return int(list(dict(row).values())[0])


@pytest.fixture
def as_admin():
    """The admin doing the deleting — only its id is read, and it must differ."""
    return {"id": -1, "email": "admin@example.com", "role": "admin"}


#: These tests delete the people they make, but a failure halfway leaves one
#: behind and the next run inherits it. Clearing first keeps a red run from
#: turning into a differently-red one.
@pytest.fixture(autouse=True)
async def _clean(database):
    for email in ("delete-me@example.com", "delete-me-2@example.com"):
        await database.execute("DELETE FROM users WHERE email = ?", (email,))
    await database.commit()


@pytest.mark.asyncio
async def test_a_user_with_a_running_campaign_can_still_be_deleted(database, as_admin):
    user_id = await _make_user(database)
    account_id = await db.create_sending_account(
        database, user_id=user_id, name="sender", platform="tiktok"
    )
    campaign_id = await db.create_outreach_campaign(
        database, user_id=user_id, name="mid-flight", message_template="hi {name}"
    )
    await db.update_outreach_campaign(database, campaign_id, status=CAMPAIGN_RUNNING)
    from services.outreach import importer

    await importer.import_targets(
        database, campaign_id, "username,profile_url\nsomeone,\n"
    )

    result = await main.admin_delete_user(user_id, admin=as_admin)

    assert result == {"ok": True}
    assert await db.get_user(database, user_id) is None
    assert await _count(
        database, "SELECT COUNT(*) FROM outreach_campaigns WHERE id = ?", (campaign_id,)
    ) == 0
    assert await _count(
        database, "SELECT COUNT(*) FROM outreach_sending_accounts WHERE id = ?", (account_id,)
    ) == 0
    # Targets and jobs hang off the campaign and go with it.
    assert await _count(
        database, "SELECT COUNT(*) FROM outreach_targets WHERE campaign_id = ?", (campaign_id,)
    ) == 0


@pytest.mark.asyncio
async def test_every_outreach_table_that_points_at_the_user_is_cleared(database, as_admin):
    """Not just campaigns: six tables name the user, and any one left behind
    is a foreign-key violation that fails the whole delete."""
    user_id = await _make_user(database, "delete-me-2@example.com")
    await db.create_sending_account(database, user_id=user_id, name="s2", platform="tiktok")
    await db.create_outreach_campaign(
        database, user_id=user_id, name="c2", message_template="hello"
    )
    await database.execute(
        "INSERT INTO outreach_templates (user_id, name, body) VALUES (?, ?, ?)",
        (user_id, "t", "body"),
    )
    await database.execute(
        "INSERT INTO outreach_lead_searches (user_id, platform, niche) VALUES (?, ?, ?)",
        (user_id, "instagram", "coffee"),
    )
    search_id = await _count(
        database, "SELECT MAX(id) FROM outreach_lead_searches WHERE user_id = ?", (user_id,)
    )
    await database.execute(
        "INSERT INTO outreach_leads (search_id, user_id, platform, username, profile_url) "
        "VALUES (?, ?, ?, ?, ?)",
        (search_id, user_id, "instagram", "lead", "https://x/lead"),
    )
    await database.commit()

    await main.admin_delete_user(user_id, admin=as_admin)

    for table in (
        "outreach_campaigns",
        "outreach_sending_accounts",
        "outreach_templates",
        "outreach_lead_searches",
        "outreach_leads",
    ):
        left = await _count(database, f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,))
        assert left == 0, f"{table} still has {left} rows pointing at a deleted user"


@pytest.mark.asyncio
async def test_deleting_yourself_is_still_refused(database, as_admin):
    """The one veto that stays: an admin cannot delete their own account."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await main.admin_delete_user(as_admin["id"], admin=as_admin)
    assert caught.value.status_code == 400
