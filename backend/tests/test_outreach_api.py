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
    settings = {"outreach_account_error_threshold": 3}
    await account_mgr.record_failure(
        database, account["id"], RESULT_SESSION_EXPIRED, "login wall", settings
    )
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
