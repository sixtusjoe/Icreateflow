"""What an admin can actually change about a person.

The admin user page draws a form. Most of it is greyed out and labelled,
because the users table has no phone, location, company or time zone. These
tests pin the four fields that do exist — name, role, status, email — plus
the notification switch, so the page's claim about what is real stays true.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import database as db
import main
from services.auth import hash_password


@pytest.fixture
def as_admin():
    return {"id": -1, "email": "admin@example.com", "role": "admin"}
#: The users table is not truncated between runs — only the outreach tables
#: are — so a test that renames somebody leaves that name behind and the
#: next run collides with it. Each file clears its own addresses first, and
#: touches nothing else in the table.
MINE = (
    "update-me@example.com", "renamed@example.com", "quiet@example.com",
    "taken@example.com", "free@example.com", "same@example.com",
    "listed@example.com",
)


@pytest.fixture(autouse=True)
async def _clean(database):
    for email in MINE:
        await database.execute("DELETE FROM users WHERE email = ?", (email,))
    await database.commit()


async def _user(database, email, name="Someone"):
    existing = await db.get_user_by_email(database, email)
    if existing:
        return dict(existing)["id"]
    return await db.create_user(database, email, hash_password("x" * 12), name)


@pytest.mark.asyncio
async def test_the_four_real_fields_are_accepted(database, as_admin):
    uid = await _user(database, "update-me@example.com")

    out = await main.admin_update_user(
        uid,
        main.AdminUserUpdate(name="Renamed", role="admin", status="suspended",
                             email="Renamed@Example.COM"),
        admin=as_admin,
    )

    assert out["name"] == "Renamed"
    assert out["role"] == "admin"
    assert out["status"] == "suspended"
    # Lower-cased on the way in, because sign-in looks it up that way.
    assert out["email"] == "renamed@example.com"


@pytest.mark.asyncio
async def test_email_notifications_can_be_turned_off(database, as_admin):
    """`False` is a real value, so the endpoint must not drop it as falsy."""
    uid = await _user(database, "quiet@example.com")

    await main.admin_update_user(
        uid, main.AdminUserUpdate(email_notifications=False), admin=as_admin)
    after = dict(await db.get_user(database, uid))
    assert after["email_notifications"] is False

    await main.admin_update_user(
        uid, main.AdminUserUpdate(email_notifications=True), admin=as_admin)
    assert dict(await db.get_user(database, uid))["email_notifications"] is True


@pytest.mark.asyncio
async def test_taking_somebody_elses_email_is_refused(database, as_admin):
    """The column is unique. Without this check the caller gets a 500 from
    the driver instead of a sentence they can act on."""
    first = await _user(database, "taken@example.com", "First")
    second = await _user(database, "free@example.com", "Second")

    with pytest.raises(HTTPException) as caught:
        await main.admin_update_user(
            second, main.AdminUserUpdate(email="taken@example.com"), admin=as_admin)
    assert caught.value.status_code == 400
    assert "already uses" in caught.value.detail
    # And the row is untouched.
    assert dict(await db.get_user(database, second))["email"] == "free@example.com"
    assert dict(await db.get_user(database, first))["email"] == "taken@example.com"


@pytest.mark.asyncio
async def test_keeping_your_own_email_is_not_a_clash(database, as_admin):
    uid = await _user(database, "same@example.com")
    out = await main.admin_update_user(
        uid, main.AdminUserUpdate(name="Still Me", email="same@example.com"), admin=as_admin)
    assert out["email"] == "same@example.com"
    assert out["name"] == "Still Me"


@pytest.mark.asyncio
async def test_the_list_carries_the_switch_but_never_the_hash(database, as_admin):
    """The admin page reads one person out of the list — there is no
    GET /api/admin/users/{id} — so the list has to carry what the page
    edits, and nothing it does not."""
    await _user(database, "listed@example.com")
    rows = await main.admin_list_users(admin=as_admin)
    row = next(r for r in rows if r["email"] == "listed@example.com")
    assert "email_notifications" in row
    assert "password_hash" not in row
    assert "unsubscribe_token" not in row
