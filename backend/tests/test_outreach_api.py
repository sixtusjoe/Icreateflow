"""API surface: authorization, ownership isolation, and secret handling.

The router is mounted on a bare FastAPI app with stub auth dependencies —
the real ones are JWT plumbing tested elsewhere, and injecting them is
exactly what `build_router` exists for.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from sqlalchemy import text

import database as db
from routers import outreach as outreach_router
from services.outreach.crypto import decrypt_session

#: Mutated per test to change who is calling.
CURRENT_USER: dict = {}


async def _stub_current_user():
    if not CURRENT_USER:
        raise HTTPException(401, "Not authenticated")
    return dict(CURRENT_USER)


async def _stub_admin_required():
    user = await _stub_current_user()
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


@pytest.fixture
async def client(database, user):
    app = FastAPI()
    app.include_router(
        outreach_router.build_router(_stub_current_user, _stub_admin_required)
    )
    CURRENT_USER.clear()
    CURRENT_USER.update(user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    CURRENT_USER.clear()


def _as(user_dict: dict) -> None:
    CURRENT_USER.clear()
    CURRENT_USER.update(user_dict)


# --- campaigns -------------------------------------------------------------

async def test_create_and_list_a_campaign(client):
    created = await client.post("/api/outreach/campaigns", json={
        "name": "Q3 outreach",
        "message_template": "Hi {{username}}, about {{offer}}",
        "template_vars": {"offer": "our beta"},
    })
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "Q3 outreach"
    assert body["status"] == "draft"
    assert body["progress"] == 0.0

    listed = await client.get("/api/outreach/campaigns")
    assert [c["id"] for c in listed.json()] == [body["id"]]


async def test_a_broken_template_is_rejected_at_create_time(client):
    response = await client.post("/api/outreach/campaigns", json={
        "name": "Bad", "message_template": "Hi {{user-name}}",
    })
    assert response.status_code == 400
    assert "Malformed" in response.json()["detail"]


async def test_import_endpoint_returns_the_summary(client):
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()

    response = await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\nbob\nalice\n!!!\n"},
    )
    assert response.status_code == 200
    assert response.json() | {"invalid_rows": None} == {
        "imported": 4, "duplicates": 1, "invalid": 1, "ready": 2,
        "invalid_rows": None, "invalid_truncated": 0,
    }


async def test_starting_without_targets_or_accounts_is_refused(client):
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    response = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    assert response.status_code == 400
    errors = response.json()["detail"]["errors"]
    assert any("No queued targets" in e for e in errors)
    assert any("No enabled sending account" in e for e in errors)


async def test_full_control_flow_start_pause_resume_stop(client, account_factory):
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\nbob\n"},
    )

    started = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    assert started.json()["jobs_queued"] == 2
    assert started.json()["campaign"]["status"] == "running"

    paused = await client.post(f"/api/outreach/campaigns/{campaign['id']}/pause")
    assert paused.json()["campaign"]["status"] == "paused"

    resumed = await client.post(f"/api/outreach/campaigns/{campaign['id']}/resume")
    assert resumed.json()["campaign"]["status"] == "running"

    stopped = await client.post(f"/api/outreach/campaigns/{campaign['id']}/stop")
    assert stopped.json()["campaign"]["status"] == "stopped"


async def test_progress_endpoint_reports_live_counters(client, account_factory):
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\nbob\n"},
    )
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")

    body = (await client.get(f"/api/outreach/campaigns/{campaign['id']}/progress")).json()
    assert body["status"] == "running"
    assert body["total_targets"] == 2
    assert body["queued_count"] == 2
    assert body["successful_count"] == 0


async def test_export_returns_csv(client, account_factory):
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    response = await client.get(f"/api/outreach/campaigns/{campaign['id']}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "alice" in response.text
    assert response.text.splitlines()[0].startswith("username,profile_url,status")


async def test_a_running_campaigns_message_cannot_be_edited(client, account_factory):
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")

    response = await client.put(
        f"/api/outreach/campaigns/{campaign['id']}",
        json={"message_template": "Something else for {{username}}"},
    )
    assert response.status_code == 400


async def test_a_running_campaign_cannot_change_what_it_does(client, account_factory):
    """Switching activity mid-run splits a campaign in two and records neither.

    Half the targets would be messaged and half followed, with nothing on
    the target row saying which it got — the counters cannot tell them
    apart afterwards, so the run is unauditable. Editing the message was
    already refused for the same reason; this closes the rest of it.
    """
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")

    for payload in (
        {"activity": "follow"},
        {"target_url": "https://www.tiktok.com/@x/video/1"},
        {"comment_count": 5},
        {"comment_variations": ["nice"]},
    ):
        response = await client.put(
            f"/api/outreach/campaigns/{campaign['id']}", json=payload
        )
        assert response.status_code == 400, payload
        assert "pause" in response.json()["detail"].lower()

    # and nothing was written on the way past
    after = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert after["campaign"]["activity"] == "message"


async def test_a_running_campaign_can_still_be_renamed_and_throttled(
    client, account_factory
):
    """The freeze is about what it sends, not about operating it.

    Throttling a run down is how you react to a campaign going badly; a
    guard that blocked it would make the guard the problem.
    """
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")

    response = await client.put(
        f"/api/outreach/campaigns/{campaign['id']}",
        json={"name": "Renamed mid-run", "max_jobs": 5, "description": "why"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed mid-run"
    assert response.json()["max_jobs"] == 5


async def test_a_paused_campaign_can_change_what_it_does(client, account_factory):
    """The guard has to lift, or pausing would not be the way through it."""
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/pause")

    response = await client.put(
        f"/api/outreach/campaigns/{campaign['id']}", json={"activity": "follow"}
    )
    assert response.status_code == 200
    assert response.json()["activity"] == "follow"


# --- authorization ---------------------------------------------------------

async def test_another_user_cannot_see_or_touch_your_campaign(client, user):
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "Private", "message_template": "Hi {{username}}",
    })).json()

    _as({"id": user["id"] + 999, "role": "user", "name": "Someone else"})
    assert (await client.get("/api/outreach/campaigns")).json() == []
    assert (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).status_code == 403
    assert (await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/start"
    )).status_code == 403
    assert (await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text", json={"content": "username\nx\n"}
    )).status_code == 403
    assert (await client.delete(
        f"/api/outreach/campaigns/{campaign['id']}"
    )).status_code == 403


async def test_another_user_cannot_control_your_sending_account(client, account_factory, user):
    account = await account_factory()
    _as({"id": user["id"] + 999, "role": "user", "name": "Someone else"})

    assert (await client.get("/api/outreach/accounts")).json() == []
    assert (await client.put(
        f"/api/outreach/accounts/{account['id']}", json={"enabled": False}
    )).status_code == 403
    assert (await client.post(
        f"/api/outreach/accounts/{account['id']}/session",
        json={"session_state": {"cookies": [{"name": "x"}]}},
    )).status_code == 403
    assert (await client.delete(
        f"/api/outreach/accounts/{account['id']}"
    )).status_code == 403


async def test_an_admin_sees_everything(client, user, account_factory):
    await account_factory()
    _as({"id": user["id"] + 999, "role": "admin", "name": "Admin"})
    assert len((await client.get("/api/outreach/accounts")).json()) == 1


async def test_unauthenticated_requests_are_rejected(client):
    CURRENT_USER.clear()
    assert (await client.get("/api/outreach/campaigns")).status_code == 401


async def test_settings_require_admin(client, user):
    assert (await client.get("/api/outreach/settings")).status_code == 403
    _as({"id": user["id"], "role": "admin", "name": "Admin"})
    body = (await client.get("/api/outreach/settings")).json()
    assert "outreach_retry_limit" in body["values"]
    assert "mock" in body["drivers"]


async def test_settings_only_accept_known_keys(client, user):
    _as({"id": user["id"], "role": "admin", "name": "Admin"})
    bad = await client.put("/api/outreach/settings", json={"values": {"site_name": "pwned"}})
    assert bad.status_code == 400
    good = await client.put(
        "/api/outreach/settings", json={"values": {"outreach_retry_limit": 5}}
    )
    assert good.json()["values"]["outreach_retry_limit"] == 5


async def test_the_headless_switch_is_settable(client, user):
    """The admin switch that decides whether browsers appear on screen.

    Defaults to hidden. It is a 0/1 setting rather than a boolean because
    the whole SPEC is numeric and the endpoint clamps by its bounds — which
    is also what stops a stray value from leaving the sender in a state
    that is neither.
    """
    _as({"id": user["id"], "role": "admin", "name": "Admin"})
    body = (await client.get("/api/outreach/settings")).json()
    assert body["values"]["outreach_headless"] == 1, "hidden is the default"
    assert body["spec"]["outreach_headless"] == {"default": 1, "min": 0, "max": 1}

    shown = await client.put(
        "/api/outreach/settings", json={"values": {"outreach_headless": 0}}
    )
    assert shown.json()["values"]["outreach_headless"] == 0
    hidden = await client.put(
        "/api/outreach/settings", json={"values": {"outreach_headless": 1}}
    )
    assert hidden.json()["values"]["outreach_headless"] == 1


async def test_the_workers_kill_switch_is_settable(client, user):
    _as({"id": user["id"], "role": "admin", "name": "Admin"})
    off = await client.put(
        "/api/outreach/settings", json={"values": {"outreach_workers_enabled": False}}
    )
    assert off.json()["values"]["outreach_workers_enabled"] is False
    on = await client.put(
        "/api/outreach/settings", json={"values": {"outreach_workers_enabled": True}}
    )
    assert on.json()["values"]["outreach_workers_enabled"] is True


# --- accounts --------------------------------------------------------------

async def test_account_limit_is_enforced(client):
    from services.outreach import config as cfg

    for i in range(cfg.MAX_SENDING_ACCOUNTS):
        assert (await client.post(
            "/api/outreach/accounts", json={"name": f"Sender {i}"}
        )).status_code == 200
    over = await client.post("/api/outreach/accounts", json={"name": "One too many"})
    assert over.status_code == 400
    assert "limit" in over.json()["detail"].lower()


async def test_a_session_is_stored_encrypted_and_never_returned(client, database):
    account = (await client.post(
        "/api/outreach/accounts", json={"name": "Sender"}
    )).json()
    assert account["has_session"] is False
    assert "session_state_encrypted" not in account

    state = {"cookies": [{"name": "sessionid", "value": "super-secret-cookie"}],
             "origins": []}
    updated = (await client.post(
        f"/api/outreach/accounts/{account['id']}/session",
        json={"session_state": state},
    )).json()
    assert updated["has_session"] is True
    assert "session_state_encrypted" not in updated
    assert "super-secret-cookie" not in json.dumps(updated)

    # It is on disk encrypted, and readable only with the app secret.
    row = dict(await db.get_sending_account(database, account["id"]))
    assert "super-secret-cookie" not in row["session_state_encrypted"]
    assert json.loads(decrypt_session(row["session_state_encrypted"])) == state

    # And no listing or detail view leaks it either.
    listed = (await client.get("/api/outreach/accounts")).json()
    detail = (await client.get(f"/api/outreach/accounts/{account['id']}")).json()
    assert "super-secret-cookie" not in json.dumps(listed) + json.dumps(detail)


async def test_a_session_payload_that_is_not_storage_state_is_rejected(client):
    account = (await client.post(
        "/api/outreach/accounts", json={"name": "Sender"}
    )).json()
    for payload in ({"password": "hunter2"}, "not json at all", ""):
        response = await client.post(
            f"/api/outreach/accounts/{account['id']}/session",
            json={"session_state": payload},
        )
        assert response.status_code == 400


async def test_disabling_and_re_enabling_an_account(client, database, account_factory):
    from services.outreach import accounts as account_mgr
    from services.outreach.constants import RESULT_SESSION_EXPIRED

    account = await account_factory()
    disabled = (await client.put(
        f"/api/outreach/accounts/{account['id']}", json={"enabled": False}
    )).json()
    assert disabled["enabled"] is False

    # An auto-pause is cleared by re-enabling.
    # (Nothing auto-pauses an account any more; one put there by hand is
    # still cleared by re-enabling.)
    await database.session.execute(text(
        "UPDATE outreach_sending_accounts SET status = 'paused', paused_reason = 'x' WHERE id = :id"
    ), {"id": account["id"]})
    await database.session.commit()
    enabled = (await client.put(
        f"/api/outreach/accounts/{account['id']}", json={"enabled": True}
    )).json()
    assert enabled["enabled"] is True
    assert enabled["status"] == "idle"
    assert enabled["paused_reason"] is None


async def test_assigning_an_account_of_the_wrong_platform_is_refused(
    client, database, account_factory
):
    account = await account_factory()
    await db.update_sending_account(database, account["id"], platform="instagram")
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    response = await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/accounts/{account['id']}"
    )
    assert response.status_code == 400


async def test_assignment_round_trip(client, account_factory):
    account = await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    assigned = await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/accounts/{account['id']}"
    )
    assert assigned.json()["assigned_account_ids"] == [account["id"]]
    removed = await client.delete(
        f"/api/outreach/campaigns/{campaign['id']}/accounts/{account['id']}"
    )
    assert removed.json()["assigned_account_ids"] == []


# --- templates -------------------------------------------------------------

async def test_template_crud_and_preview(client):
    created = (await client.post("/api/outreach/templates", json={
        "name": "Intro", "body": "Hi {{username}}, about {{offer}}",
        "defaults": {"offer": "our beta"},
    })).json()
    assert created["name"] == "Intro"

    listed = (await client.get("/api/outreach/templates")).json()
    assert listed[0]["variables"] == ["username", "offer"]

    preview = (await client.post("/api/outreach/templates/preview", json={
        "body": "Hi {{username}}, about {{offer}}", "variables": {"offer": "our beta"},
    })).json()
    assert preview["preview"] == "Hi creator_handle, about our beta"

    updated = (await client.put(
        f"/api/outreach/templates/{created['id']}", json={"name": "Intro v2"}
    )).json()
    assert updated["name"] == "Intro v2"

    assert (await client.delete(
        f"/api/outreach/templates/{created['id']}"
    )).json() == {"ok": True}
    assert (await client.get("/api/outreach/templates")).json() == []


async def test_preview_reports_a_broken_template(client):
    response = await client.post(
        "/api/outreach/templates/preview", json={"body": "Hi {{oops"}
    )
    assert response.status_code == 400


# --- audit -----------------------------------------------------------------

async def test_campaign_actions_are_audited(client, account_factory):
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/pause")

    actions = [a["action"] for a in (await client.get("/api/outreach/audit")).json()]
    assert "campaign.created" in actions
    assert "campaign.targets_imported" in actions
    assert "campaign.started" in actions
    assert "campaign.paused" in actions


# --- watching the sign-in browser from the page ----------------------------

async def test_a_viewer_ticket_is_only_issued_for_your_own_account(
    client, database, user
):
    """Otherwise a ticket is a way to watch someone else sign in."""
    from services.outreach import local_browser, session_viewer

    account_id = (await client.post("/api/outreach/accounts", json={
        "name": "Watched", "platform": "instagram",
    })).json()["id"]

    session_viewer.clear()
    import os
    os.environ["ICREATE_OUTREACH_LOCAL_BROWSER"] = "1"
    try:
        assert local_browser.is_enabled()
        mine = await client.post(
            f"/api/outreach/accounts/{account_id}/session/viewer-ticket")
        assert mine.status_code == 200, mine.text
        body = mine.json()
        assert body["ticket"] and len(body["ticket"]) >= 32
        assert body["path"].endswith(f"/accounts/{account_id}/session/stream")

        _as({"id": user["id"] + 999, "role": "user", "name": "Someone else"})
        theirs = await client.post(
            f"/api/outreach/accounts/{account_id}/session/viewer-ticket")
        assert theirs.status_code in (403, 404), theirs.status_code
    finally:
        os.environ.pop("ICREATE_OUTREACH_LOCAL_BROWSER", None)
        session_viewer.clear()


async def test_no_viewer_ticket_where_browser_sign_in_is_switched_off(client):
    """A host with no display must not hand out passes to a browser it
    cannot open — the live server ran that way for months."""
    import os
    from services.outreach import session_viewer

    account_id = (await client.post("/api/outreach/accounts", json={
        "name": "Unwatched", "platform": "instagram",
    })).json()["id"]
    os.environ.pop("ICREATE_OUTREACH_LOCAL_BROWSER", None)
    os.environ.pop("ICREATE_OUTREACH_BROWSER_LOGIN", None)
    session_viewer.clear()
    r = await client.post(
        f"/api/outreach/accounts/{account_id}/session/viewer-ticket")
    assert r.status_code == 400
    assert "switched off" in r.json()["detail"].lower()
    assert session_viewer.outstanding() == 0


async def test_a_proxy_is_stored_encrypted_and_its_password_never_returned(
    client, database
):
    """Four accounts on one server share one IP, which is the most obvious
    thing about them. A proxy each is the fix, and it carries a password.
    """
    account = (await client.post(
        "/api/outreach/accounts", json={"name": "Proxied"}
    )).json()
    assert account["proxy"] is None

    updated = (await client.put(
        f"/api/outreach/accounts/{account['id']}",
        json={"proxy_url": "http://user123:s3cret@gate.example.net:7000"},
    )).json()

    # The host comes back so the page can show where an account goes out
    # through. The password does not, anywhere.
    assert updated["proxy"] == "http://user123@gate.example.net:7000"
    assert "s3cret" not in json.dumps(updated)
    assert "proxy_url_encrypted" not in updated

    row = dict(await db.get_sending_account(database, account["id"]))
    assert "s3cret" not in (row["proxy_url_encrypted"] or "")
    assert decrypt_session(row["proxy_url_encrypted"]) == (
        "http://user123:s3cret@gate.example.net:7000")

    listed = (await client.get("/api/outreach/accounts")).json()
    assert "s3cret" not in json.dumps(listed)


async def test_a_proxy_a_browser_cannot_use_is_refused(client):
    """Chromium cannot authenticate to SOCKS5. Accepting it would mean the
    account quietly sends from the server's own address — the exact thing
    the proxy was bought to prevent."""
    account = (await client.post(
        "/api/outreach/accounts", json={"name": "Bad proxy"}
    )).json()
    bad = await client.put(
        f"/api/outreach/accounts/{account['id']}",
        json={"proxy_url": "socks5://user:pass@gate.example.net:1080"},
    )
    assert bad.status_code == 400
    assert "socks5" in bad.json()["detail"].lower()


async def test_clearing_a_proxy_returns_the_account_to_this_server(client, database):
    account = (await client.post(
        "/api/outreach/accounts", json={"name": "Cleared"}
    )).json()
    await client.put(f"/api/outreach/accounts/{account['id']}",
                     json={"proxy_url": "http://gate.example.net:7000"})
    cleared = (await client.put(
        f"/api/outreach/accounts/{account['id']}", json={"proxy_url": ""}
    )).json()
    assert cleared["proxy"] is None
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["proxy_url_encrypted"] is None


async def test_starting_or_resuming_clears_a_platform_cooldown(client, account_factory, database):
    """A running campaign must never carry a pause deadline.

    Both are operator overrides: they decided to go now, whatever the
    platform said. Leaving `paused_until` set means the countdown does not
    show (the status is `running`), and when that stale deadline passes the
    resume sweep picks up a campaign that never stopped and logs a cooldown
    clearing nobody was waiting on.

    The bug was real: `resume` cleared the fields and `start` did not.
    """
    from sqlalchemy import text as _text

    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\nbob\n"},
    )

    async def strand_under_a_cooldown(status: str) -> None:
        await database.session.execute(
            _text("UPDATE outreach_campaigns "
                  "   SET status = :st, "
                  "       paused_until = (NOW() AT TIME ZONE 'UTC') + INTERVAL '6 hours', "
                  "       paused_reason = 'follow limit reached' "
                  " WHERE id = :cid"),
            {"cid": campaign["id"], "st": status},
        )
        await database.session.commit()

    async def deadline():
        row = (await database.session.execute(
            _text("SELECT status, paused_until FROM outreach_campaigns WHERE id = :cid"),
            {"cid": campaign["id"]},
        )).mappings().first()
        return dict(row)

    # start
    await strand_under_a_cooldown("paused")
    started = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    assert started.status_code == 200, started.text
    after = await deadline()
    assert after["status"] == "running"
    assert after["paused_until"] is None, (
        "start left a stale cooldown on a running campaign"
    )

    # resume
    await strand_under_a_cooldown("paused")
    resumed = await client.post(f"/api/outreach/campaigns/{campaign['id']}/resume")
    assert resumed.status_code == 200, resumed.text
    after = await deadline()
    assert after["status"] == "running"
    assert after["paused_until"] is None, (
        "resume left a stale cooldown on a running campaign"
    )


async def test_a_follow_or_comment_campaign_needs_no_message_template(client):
    """The client omits the field for activities that send nothing.

    `message_template` is NOT NULL with a server default of "" — but a
    default only applies to a column left out of the INSERT. Pydantic fills
    an absent optional with None, which went to Postgres as an explicit
    NULL and came back a 500, so no follow or comment campaign could be
    created at all.
    """
    for activity, extra in (
        ("follow", {}),
        ("comment", {"target_url": "https://www.tiktok.com/@a/video/123",
                     "comment_count": 2, "comment_variations": ["nice", "great"]}),
    ):
        created = await client.post("/api/outreach/campaigns", json={
            "name": f"{activity} campaign", "activity": activity, **extra,
        })
        assert created.status_code == 200, (
            f"{activity} campaign refused: {created.status_code} {created.text}"
        )
        body = created.json()
        assert body["activity"] == activity
        assert body["message_template"] == "", (
            "an absent template should be stored empty, not null"
        )


async def test_a_message_campaign_still_requires_a_usable_template(client):
    """The fix must not make a message campaign's template optional."""
    bad = await client.post("/api/outreach/campaigns", json={
        "name": "broken", "activity": "message",
        "message_template": "Hi {{ unclosed",
    })
    assert bad.status_code == 400


async def test_the_export_can_be_narrowed_to_a_status_and_a_count(client, account_factory):
    """Exporting seven thousand rows to filter them in a spreadsheet is
    what people were doing instead of this."""
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "E", "message_template": "Hi {{username}}", "platform": "instagram",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\nbob\ncarol\n"},
    )

    full = await client.get(f"/api/outreach/campaigns/{campaign['id']}/export.csv")
    assert full.status_code == 200
    assert len(full.text.strip().splitlines()) == 4        # header + three

    capped = await client.get(
        f"/api/outreach/campaigns/{campaign['id']}/export.csv?limit=2")
    assert len(capped.text.strip().splitlines()) == 3      # header + two

    queued = await client.get(
        f"/api/outreach/campaigns/{campaign['id']}/export.csv?status=queued")
    assert len(queued.text.strip().splitlines()) == 4
    none_sent = await client.get(
        f"/api/outreach/campaigns/{campaign['id']}/export.csv?status=sent")
    assert len(none_sent.text.strip().splitlines()) == 1   # header only

    bad = await client.get(
        f"/api/outreach/campaigns/{campaign['id']}/export.csv?status=nonsense")
    assert bad.status_code == 400


async def test_a_links_only_export_carries_the_platforms_own_urls(client, account_factory):
    """The shape you want when the list is going somewhere that takes links."""
    await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "L", "message_template": "Hi {{username}}", "platform": "instagram",
    })).json()
    await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/import-text",
        json={"content": "username\nalice\n"},
    )
    res = await client.get(
        f"/api/outreach/campaigns/{campaign['id']}/export.csv?links_only=true")
    lines = res.text.strip().splitlines()
    assert lines[0].strip() == "username,profile_url"
    assert "instagram.com/alice" in lines[1]
    assert "links" in res.headers["content-disposition"]


# --- what a search found ---------------------------------------------------


async def _search_with_leads(database, user, count: int, platform: str = "tiktok") -> int:
    from sqlalchemy import text

    search_id = (await database.session.execute(text(
        "INSERT INTO outreach_lead_searches "
        "  (user_id, campaign_id, platform, niche, wanted, status) "
        "VALUES (:uid, NULL, :p, 'big read', :n, 'cancelled') RETURNING id"),
        {"uid": user["id"], "p": platform, "n": count})).scalar_one()
    await database.session.execute(text(
        "INSERT INTO outreach_leads (search_id, user_id, platform, username, profile_url) "
        "SELECT :s, :uid, :p, 'lead' || g, 'https://www.tiktok.com/@lead' || g "
        "  FROM generate_series(1, :n) g"),
        {"s": search_id, "uid": user["id"], "p": platform, "n": count})
    await database.session.commit()
    return int(search_id)


async def test_a_search_lists_everyone_it_found_not_the_first_500(client, database, user):
    """Measured 2026-09-24: search #43 banked 638 leads, the page said 500.

    The list quietly stopped at a default of 500, so the counter dropped when
    the search stopped — and "Select all" would have imported 500 of 638,
    stranding the rest.
    """
    search_id = await _search_with_leads(database, user, 638)
    response = await client.get(f"/api/outreach/leads/searches/{search_id}/leads")
    assert response.status_code == 200
    assert len(response.json()) == 638


async def test_leads_in_no_campaign_are_all_offered(client, database, user):
    await _search_with_leads(database, user, 1200)
    response = await client.get("/api/outreach/leads/pending",
                                params={"platform": "tiktok"})
    assert response.status_code == 200
    assert len(response.json()) == 1200


# --- a refused message stops the campaign, not the account -----------------


async def test_a_refused_message_pauses_the_campaign_until_the_wording_changes(
        client, database, account_factory, settings):
    """TikTok refused one campaign's text and paused RealMic — which stopped
    every other campaign RealMic served, over words only one of them used."""
    from services.outreach import runner
    from services.outreach.browser.mock import MockMessenger
    from services.outreach.constants import RESULT_MESSAGE_REFUSED

    account = await account_factory()
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Buy now at t.me/somewhere",
    })).json()
    cid = campaign["id"]
    await client.post(f"/api/outreach/campaigns/{cid}/import-text",
                      json={"content": "username\nalice\nbob\n"})
    assert (await client.post(f"/api/outreach/campaigns/{cid}/start")).status_code == 200

    driver = MockMessenger(default=(RESULT_MESSAGE_REFUSED, "refused"))
    worker = runner.OutreachWorker(worker_id="t", driver=driver, once=True)
    assert await worker.process_one(settings) is True

    # The account is untouched…
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] != "paused"
    assert row["consecutive_errors"] == 0

    # …and the campaign stands down with no clock, saying why.
    detail = (await client.get(f"/api/outreach/campaigns/{cid}")).json()["campaign"]
    assert detail["status"] == "paused"
    assert detail["paused_until"] is None
    assert "refused" in detail["paused_reason"]
    assert detail["message_refused"] is True
    progress = (await client.get(f"/api/outreach/campaigns/{cid}/progress")).json()
    assert progress["message_refused"] is True and progress["paused_reason"]

    # Same words: no.
    blocked = await client.post(f"/api/outreach/campaigns/{cid}/resume")
    assert blocked.status_code == 400
    assert "refused this exact message" in str(blocked.json())

    # New words: yes, and the record of the refusal goes with the resume.
    await client.put(f"/api/outreach/campaigns/{cid}",
                     json={"message_template": "Hi {{username}}, loved your post"})
    assert (await client.get(f"/api/outreach/campaigns/{cid}")).json()[
        "campaign"]["message_refused"] is False
    resumed = await client.post(f"/api/outreach/campaigns/{cid}/resume")
    assert resumed.status_code == 200, resumed.text
    after = resumed.json()["campaign"]
    assert after["status"] == "running"
    assert after["paused_reason"] is None and after["message_refused"] is False


async def test_an_account_refused_on_two_different_messages_is_the_account(
        client, database, account_factory, settings):
    """RealMic had campaign 14 refused, the wording was changed, and that
    was refused too; a plain test message to the operator was then refused
    the same way. The app kept saying "change the wording". Two different
    messages refused from one account means TikTok is refusing the account."""
    from services.outreach import runner
    from services.outreach.browser.mock import MockMessenger
    from services.outreach.constants import RESULT_MESSAGE_REFUSED

    account = await account_factory()
    cid = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "First wording",
    })).json()["id"]
    await client.post(f"/api/outreach/campaigns/{cid}/import-text",
                      json={"content": "username\nalice\nbob\ncarol\n"})
    assert (await client.post(f"/api/outreach/campaigns/{cid}/start")).status_code == 200

    refusing = MockMessenger(default=(RESULT_MESSAGE_REFUSED, "refused"))
    worker = runner.OutreachWorker(worker_id="t", driver=refusing, once=True)
    assert await worker.process_one(settings) is True

    # One refusal can't tell the words from the account, and says so.
    first = (await client.get(f"/api/outreach/campaigns/{cid}")).json()["campaign"]
    assert first["message_refused"] is True and first["account_refused"] is False
    assert "account is fine" not in first["paused_reason"]
    assert "wording or" in first["paused_reason"]

    await client.put(f"/api/outreach/campaigns/{cid}",
                     json={"message_template": "Second wording"})
    assert (await client.post(f"/api/outreach/campaigns/{cid}/resume")).status_code == 200
    assert await worker.process_one(settings) is True

    # Refused again on different words: it's the account.
    second = (await client.get(f"/api/outreach/campaigns/{cid}")).json()["campaign"]
    assert second["status"] == "paused"
    assert second["account_refused"] is True and second["message_refused"] is False
    assert "refusing that account" in second["paused_reason"]
    progress = (await client.get(f"/api/outreach/campaigns/{cid}/progress")).json()
    assert progress["account_refused"] is True
    # Still not paused: nothing pauses an account.
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] != "paused"

    # Nothing holds the campaign to new words, and the resume clears the flag.
    resumed = await client.post(f"/api/outreach/campaigns/{cid}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["campaign"]["account_refused"] is False

    # A delivered message clears the account's record.
    sending = runner.OutreachWorker(worker_id="t2", driver=MockMessenger(), once=True)
    assert await sending.process_one(settings) is True
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["refused_template"] is None


# --- unfollow campaigns ----------------------------------------------------


async def test_an_unfollow_campaign_unfollows_and_needs_no_message(
        client, database, account_factory, settings):
    from services.outreach import runner
    from services.outreach.browser.mock import MockMessenger

    await account_factory()
    # Unfollow undoes only ICREATEFLOW's own follows, so alice is followed
    # by a follow campaign first.
    follows = (await client.post("/api/outreach/campaigns", json={
        "name": "Grow", "activity": "follow", "platform": "tiktok"})).json()
    await client.post(f"/api/outreach/campaigns/{follows['id']}/import-text",
                      json={"content": "username\nalice\n"})
    await client.post(f"/api/outreach/campaigns/{follows['id']}/start")
    assert await runner.OutreachWorker(worker_id="f", driver=MockMessenger(), once=True).process_one(settings)
    await client.post(f"/api/outreach/campaigns/{follows['id']}/stop")
    await database.session.execute(text("UPDATE outreach_sending_accounts SET last_activity_at = NULL"))
    await database.session.commit()

    created = await client.post("/api/outreach/campaigns", json={
        "name": "Clean up", "activity": "unfollow", "platform": "tiktok",
    })
    assert created.status_code == 200, created.text
    cid = created.json()["id"]
    await client.post(f"/api/outreach/campaigns/{cid}/import-text",
                      json={"content": "username\nalice\n"})
    started = await client.post(f"/api/outreach/campaigns/{cid}/start")
    assert started.status_code == 200, started.text

    driver = MockMessenger()
    worker = runner.OutreachWorker(worker_id="t", driver=driver, once=True)
    assert await worker.process_one(settings) is True
    assert [u for _, u in driver.unfollowed] == ["alice"]
    assert driver.followed == [], "an unfollow campaign followed somebody"


async def test_unfollow_is_refused_where_it_is_not_built(client):
    response = await client.post("/api/outreach/campaigns", json={
        "name": "X", "activity": "unfollow", "platform": "x",
    })
    assert response.status_code == 400
    assert "TikTok and Instagram" in response.text


def test_an_unfollow_on_an_account_with_a_phone_goes_to_the_phone():
    from services.outreach.runner import OutreachWorker
    w = OutreachWorker()
    assert w._driver_name_for({}, "tiktok", via_phone=True) == "android_tiktok"


async def test_a_follow_campaign_with_no_message_can_start(client, account_factory):
    """The dialog stores no message on a follow campaign; Start refused it
    with "Message template is empty"."""
    await account_factory()
    cid = (await client.post("/api/outreach/campaigns", json={
        "name": "F", "activity": "follow", "platform": "tiktok"})).json()["id"]
    await client.post(f"/api/outreach/campaigns/{cid}/import-text",
                      json={"content": "username\nalice\n"})
    started = await client.post(f"/api/outreach/campaigns/{cid}/start")
    assert started.status_code == 200, started.text
