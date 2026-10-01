"""What a user can change about their own account.

The Account page gives a person the levers an admin has over them that are
theirs to pull: the notification switch, their profile details, and leaving.
These tests pin the three backend changes that page needed — the switch on
the profile endpoint, the profile endpoint no longer moving the email past
its emailed-code check, and deleting your own account — plus the admin's
read-only view of the profile details.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import database as db
import main
from services.auth import hash_password

#: The users table is not truncated between runs, so each file clears its
#: own addresses first and touches nothing else in the table.
MINE = (
    "self-quiet@example.com", "self-email@example.com", "self-moved@example.com",
    "self-leave@example.com", "self-wrongpw@example.com", "self-lastadmin@example.com",
    "self-profile@example.com", "self-avatar@example.com", "self-avatar2@example.com",
    "self-avatar3@example.com", "self-avatar4@example.com", "self-avatar5@example.com",
)
PASSWORD = "correct horse"


@pytest.fixture(autouse=True)
async def _clean(database):
    for email in MINE:
        await database.execute("DELETE FROM users WHERE email = ?", (email,))
    await database.commit()


async def _me(database, email, role="user"):
    uid = await db.create_user(database, email, hash_password(PASSWORD), "Self", role=role)
    return dict(await db.get_user(database, uid))


@pytest.mark.asyncio
async def test_a_user_can_turn_their_emails_back_on(database):
    """Unsubscribing used to be one-way: nothing let a user switch it back."""
    me = await _me(database, "self-quiet@example.com")

    await main.update_profile(main.ProfileUpdate(email_notifications=False), user=me)
    assert dict(await db.get_user(database, me["id"]))["email_notifications"] is False

    out = await main.update_profile(main.ProfileUpdate(email_notifications=True), user=me)
    assert out["email_notifications"] is True


@pytest.mark.asyncio
async def test_the_profile_endpoint_no_longer_moves_the_email(database):
    """The address changes only through the emailed-code flow."""
    me = await _me(database, "self-email@example.com")

    with pytest.raises(HTTPException) as e:
        await main.update_profile(main.ProfileUpdate(email="self-moved@example.com"), user=me)
    assert e.value.status_code == 400
    assert dict(await db.get_user(database, me["id"]))["email"] == "self-email@example.com"

    # Sending the address it already has is not a change, and still saves the rest.
    out = await main.update_profile(
        main.ProfileUpdate(email="Self-Email@Example.com", name="Renamed"), user=me)
    assert out["name"] == "Renamed"
    assert out["email"] == "self-email@example.com"


@pytest.mark.asyncio
async def test_a_user_can_delete_their_own_account(database):
    me = await _me(database, "self-leave@example.com")
    await db.set_user_setting(database, me["id"], "profile_phone", "+44 1")

    assert await main.delete_my_account(main.AccountDelete(password=PASSWORD), user=me) == {"ok": True}
    assert await db.get_user(database, me["id"]) is None
    assert await db.get_user_settings(database, me["id"]) == {}


@pytest.mark.asyncio
async def test_deleting_yourself_needs_your_password(database):
    me = await _me(database, "self-wrongpw@example.com")

    with pytest.raises(HTTPException) as e:
        await main.delete_my_account(main.AccountDelete(password="not it"), user=me)
    assert e.value.status_code == 400
    assert await db.get_user(database, me["id"]) is not None


@pytest.mark.asyncio
async def test_the_last_admin_cannot_delete_themselves(database):
    me = await _me(database, "self-lastadmin@example.com", role="admin")
    # The test database may hold other admins from other files. Demote them
    # for the length of this test, and put them back whatever happens.
    cur = await database.execute("SELECT id FROM users WHERE role = 'admin' AND id != ?", (me["id"],))
    others = [dict(r)["id"] for r in await cur.fetchall()]
    for uid in others:
        await database.execute("UPDATE users SET role = 'user' WHERE id = ?", (uid,))
    await database.commit()
    try:
        with pytest.raises(HTTPException) as e:
            await main.delete_my_account(main.AccountDelete(password=PASSWORD), user=me)
        assert e.value.status_code == 400
        assert await db.get_user(database, me["id"]) is not None
    finally:
        for uid in others:
            await database.execute("UPDATE users SET role = 'admin' WHERE id = ?", (uid,))
        await database.commit()


@pytest.mark.asyncio
async def test_an_admin_reads_only_the_profile_keys(database):
    """The admin sees phone, location, company and time zone — never the
    person's own API keys, which share the same table."""
    me = await _me(database, "self-profile@example.com")
    await db.set_user_setting(database, me["id"], "profile_phone", "+234 800")
    await db.set_user_setting(database, me["id"], "profile_timezone", "Africa/Lagos")
    await db.set_user_setting(database, me["id"], "openai_api_key", "sk-secret")

    out = await main.admin_user_profile(me["id"], admin={"id": -1, "role": "admin"})

    assert out == {
        "profile_phone": "+234 800",
        "profile_location": "",
        "profile_company": "",
        "profile_timezone": "Africa/Lagos",
    }


# ---------------------------------------------------------------- avatar

def _upload(data: bytes, name="me.png"):
    import io
    from starlette.datastructures import UploadFile
    return UploadFile(io.BytesIO(data), filename=name)


def _png(w=900, h=600):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 240, 60)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def avatar_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "AVATAR_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_a_picture_is_cropped_square_and_shown_to_admins(database, avatar_dir):
    from PIL import Image
    me = await _me(database, "self-avatar@example.com")

    out = await main.upload_avatar(_upload(_png()), user=me)

    name = out["avatar_url"].rsplit("/", 1)[-1]
    assert out["avatar_url"].startswith("/files/uploads/avatars/")
    with Image.open(avatar_dir / name) as img:
        assert img.size == (512, 512) and img.format == "WEBP"
    listed = [u for u in await db.get_users(database) if u["id"] == me["id"]][0]
    assert listed["avatar_url"] == out["avatar_url"]


@pytest.mark.asyncio
async def test_replacing_or_removing_a_picture_deletes_the_old_file(database, avatar_dir):
    me = await _me(database, "self-avatar2@example.com")
    first = (await main.upload_avatar(_upload(_png()), user=me))["avatar_url"]
    second = (await main.upload_avatar(_upload(_png(300, 300)), user=me))["avatar_url"]

    assert first != second
    assert not (avatar_dir / first.rsplit("/", 1)[-1]).exists()

    await main.remove_avatar(user=me)
    assert not (avatar_dir / second.rsplit("/", 1)[-1]).exists()
    assert (await db.get_user_settings(database, me["id"]))["profile_avatar"] == ""


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_picture_is_refused(database, avatar_dir):
    me = await _me(database, "self-avatar3@example.com")
    for junk in (b"<svg onload=alert(1)>", b"not an image at all"):
        with pytest.raises(HTTPException) as e:
            await main.upload_avatar(_upload(junk, "x.svg"), user=me)
        assert e.value.status_code == 400
    assert list(avatar_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_the_picture_cannot_be_set_through_plain_settings(database):
    """Otherwise it could point at any address an admin's browser would load."""
    me = await _me(database, "self-avatar4@example.com")
    with pytest.raises(HTTPException):
        await main.update_user_settings(main.SettingUpdate(key="profile_avatar", value="https://evil.example/x.png"), user=me)


@pytest.mark.asyncio
async def test_deleting_an_account_deletes_its_picture(database, avatar_dir):
    me = await _me(database, "self-avatar5@example.com")
    url = (await main.upload_avatar(_upload(_png()), user=me))["avatar_url"]
    await main.delete_my_account(main.AccountDelete(password=PASSWORD), user=me)
    assert not (avatar_dir / url.rsplit("/", 1)[-1]).exists()
