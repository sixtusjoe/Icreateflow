"""TikTok follows handed to the phone app and answered by it.

The worker runs for real (no driver handed in) against a follow campaign
whose account is linked to a phone; the phone is played by a coroutine on
its own database connection, calling the same functions the API does.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

import database as db
from routers import outreach as outreach_router
from services.outreach import companion, runner
from services.outreach.browser.mock import MockMessenger
from services.outreach.constants import (
    ACCOUNT_PAUSED,
    RESULT_DEVICE_UNAVAILABLE,
    RESULT_FOLLOW_LIMITED,
    RESULT_SENT,
    TARGET_SENT,
)
from tests.test_outreach_api import CURRENT_USER, _as, _stub_admin_required, _stub_current_user

PHONE = "phone-0123456789abcdef"
OTHER_PHONE = "phone-fedcba9876543210"


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(companion, "POLL_S", 0.05)
    monkeypatch.setattr(companion, "PICKUP_S", 1.0)
    monkeypatch.setattr(companion, "RUN_S", 1.0)


@pytest.fixture
async def follow_run(seeded, database):
    """`seeded`, as a follow campaign, its account linked to PHONE, not pinned to mock."""
    await db.update_outreach_campaign(database, seeded["campaign"]["id"], activity="follow")
    await db.update_sending_account(
        database, seeded["account"]["id"], companion_device=PHONE, device_handle="lancastar", via="phone")
    settings = dict(seeded["settings"], outreach_driver="playwright")
    return {**seeded, "settings": settings}


async def _phone(device: str, answer: str, error: str | None = None,
                 user_id=None, tries: int = 100) -> dict | None:
    """Ask for work like the app does, and answer the first follow."""
    conn = await db.get_db()
    try:
        for _ in range(tries):
            # Only ask once there is something to take: asking writes "last
            # seen" on the account, and a worker leasing it in that instant
            # skips it (SKIP LOCKED) — harmless live, a coin-flip in a test.
            waiting = (await conn.session.execute(text(
                "SELECT 1 FROM outreach_companion_tasks WHERE status = 'pending'"))).first()
            await conn.session.commit()
            if not waiting:
                await asyncio.sleep(0.02)
                continue
            task = await companion.claim(conn, device, user_id)
            if task:
                assert await companion.finish(conn, task["id"], device, answer, error, {"n": 1})
                return task
            await asyncio.sleep(0.02)
        return None
    finally:
        await conn.close()


async def _tasks(database) -> list[dict]:
    rows = await database.session.execute(text(
        "SELECT * FROM outreach_companion_tasks ORDER BY id"))
    await database.session.commit()
    return [dict(r) for r in rows.mappings()]


def _worker():
    return runner.OutreachWorker(worker_id="test-worker", once=True)


async def test_the_phone_does_the_follow_and_the_target_is_recorded(follow_run, database, quick):
    worked, task = await asyncio.gather(
        _worker().process_one(follow_run["settings"]),
        _phone(PHONE, RESULT_SENT),
    )
    assert worked is True
    assert task is not None and task["action"] == "follow" and task["handle"] == "lancastar"

    targets = await db.get_outreach_targets(database, follow_run["campaign"]["id"])
    done = [t for t in targets if t["status"] == TARGET_SENT]
    assert [t["username"] for t in done] == [task["username"]]
    assert [t["status"] for t in await _tasks(database)] == ["done"]


async def test_a_phone_that_never_asks_holds_the_follow_without_pausing_anything(
        follow_run, database, quick):
    assert await _worker().process_one(follow_run["settings"]) is True

    [task] = await _tasks(database)
    assert task["status"] == "expired"
    account = await db.get_sending_account(database, follow_run["account"]["id"])
    assert account["status"] != ACCOUNT_PAUSED
    assert "didn't pick up" in (account["last_error"] or "")
    campaign = await db.get_outreach_campaign(database, follow_run["campaign"]["id"])
    assert campaign["status"] == "running"


async def test_a_follow_given_up_on_cannot_be_claimed_or_answered_later(follow_run, database, quick):
    await _worker().process_one(follow_run["settings"])
    [task] = await _tasks(database)
    assert task["status"] == "expired"

    assert await companion.claim(database, PHONE, None) is None
    assert await companion.finish(database, task["id"], PHONE, RESULT_SENT, None, None) is False


async def test_a_claim_in_the_instant_of_giving_up_keeps_the_worker_waiting(follow_run, database):
    """The race `_expire` exists for: a claimed task is not expired as pending."""
    task_id = (await database.session.execute(text(
        "INSERT INTO outreach_companion_tasks (account_id, device_id, action, username, handle) "
        "VALUES (:a, :d, 'follow', 'alice', 'lancastar') RETURNING id"
    ), {"a": follow_run["account"]["id"], "d": PHONE})).scalar_one()
    await database.session.commit()
    assert (await companion.claim(database, PHONE, None))["id"] == task_id
    assert await companion._expire(database.session, task_id, "pending") is False


async def test_the_phones_limit_answer_stands_the_campaign_down(follow_run, database, quick):
    await asyncio.gather(
        _worker().process_one(follow_run["settings"]),
        _phone(PHONE, RESULT_FOLLOW_LIMITED, "The Follow button did not change"),
    )
    campaign = await db.get_outreach_campaign(database, follow_run["campaign"]["id"])
    assert campaign["status"] == "paused"
    assert campaign["paused_until"] is not None
    account = await db.get_sending_account(database, follow_run["account"]["id"])
    assert account["status"] != ACCOUNT_PAUSED


async def test_another_phone_gets_nothing_and_cannot_answer(follow_run, database, quick):
    worker = asyncio.create_task(_worker().process_one(follow_run["settings"]))
    try:
        for _ in range(50):
            if await _tasks(database):
                break
            await asyncio.sleep(0.02)
        assert await companion.claim(database, OTHER_PHONE, None) is None
        task = await companion.claim(database, PHONE, None)
        assert task is not None
        assert await companion.finish(database, task["id"], OTHER_PHONE, RESULT_SENT, None, None) is False
        assert await companion.finish(database, task["id"], PHONE, RESULT_SENT, None, None) is True
    finally:
        await worker


async def test_another_users_phone_cannot_claim(follow_run, database, quick):
    worker = asyncio.create_task(_worker().process_one(follow_run["settings"]))
    try:
        for _ in range(50):
            if await _tasks(database):
                break
            await asyncio.sleep(0.02)
        stranger = follow_run["account"]["user_id"] + 999
        assert await companion.claim(database, PHONE, stranger) is None
    finally:
        await worker  # expires unclaimed


async def test_unlinking_takes_back_what_the_phone_had_not_picked_up(follow_run, database, quick):
    worker = asyncio.create_task(_worker().process_one(follow_run["settings"]))
    try:
        for _ in range(50):
            if await _tasks(database):
                break
            await asyncio.sleep(0.02)
        await db.update_sending_account(database, follow_run["account"]["id"], companion_device=None)
        assert await companion.claim(database, PHONE, None) is None
    finally:
        await worker


async def test_the_mock_setting_still_wins_over_a_linked_phone(follow_run, database, quick):
    """No driver handed in — only the setting says mock, and no phone is asked."""
    settings = dict(follow_run["settings"], outreach_driver="mock")
    worker = _worker()
    assert await worker.process_one(settings) is True
    assert await _tasks(database) == []
    assert len(worker._drivers["mock"].followed) == 1


async def test_a_driver_handed_in_still_wins_over_a_linked_phone(follow_run, database, quick):
    driver = MockMessenger()
    worker = runner.OutreachWorker(worker_id="test-worker", driver=driver, once=True)
    assert await worker.process_one(follow_run["settings"]) is True
    assert len(driver.followed) == 1
    assert await _tasks(database) == []


@pytest.fixture
async def message_run(seeded, database):
    """`seeded` (a message campaign), its account a linked phone account."""
    await db.update_sending_account(
        database, seeded["account"]["id"], companion_device=PHONE, device_handle="lancastar", via="phone")
    settings = dict(seeded["settings"], outreach_driver="playwright")
    return {**seeded, "settings": settings}


async def test_a_message_goes_to_the_phone_already_written(message_run, database, quick):
    worked, task = await asyncio.gather(
        _worker().process_one(message_run["settings"]),
        _phone(PHONE, RESULT_SENT),
    )
    assert worked is True
    assert task["action"] == "message"
    # The template is filled in on the server; the phone types exactly this.
    assert task["message"] == f"Hello {task['username']}, quick question."
    targets = await db.get_outreach_targets(database, message_run["campaign"]["id"])
    assert [t["username"] for t in targets if t["status"] == TARGET_SENT] == [task["username"]]


async def test_a_refusal_from_the_phone_stops_the_campaign_not_the_account(message_run, database, quick):
    from services.outreach.constants import RESULT_MESSAGE_REFUSED
    await asyncio.gather(
        _worker().process_one(message_run["settings"]),
        _phone(PHONE, RESULT_MESSAGE_REFUSED, "may be in violation of our Community Guidelines"),
    )
    campaign = await db.get_outreach_campaign(database, message_run["campaign"]["id"])
    assert campaign["status"] == "paused" and campaign["paused_until"] is None
    account = await db.get_sending_account(database, message_run["account"]["id"])
    assert account["status"] != ACCOUNT_PAUSED


async def test_a_campaign_with_an_image_never_goes_to_a_phone_account(message_run, database, quick):
    """The phone can't attach the image, and would send the words alone."""
    await db.update_outreach_campaign(
        database, message_run["campaign"]["id"], attachment_path="/tmp/picture.png")
    driver = MockMessenger()
    worker = runner.OutreachWorker(worker_id="test-worker", driver=driver, once=True)
    assert await worker.process_one(dict(message_run["settings"])) is False
    assert await _tasks(database) == []


async def test_a_comment_campaign_never_goes_to_a_phone_account(message_run, database, quick):
    await db.update_outreach_campaign(database, message_run["campaign"]["id"], activity="comment")
    driver = MockMessenger()
    worker = runner.OutreachWorker(worker_id="test-worker", driver=driver, once=True)
    assert await worker.process_one(dict(message_run["settings"])) is False
    assert await _tasks(database) == []


async def test_a_phone_account_nobody_has_linked_says_why_and_is_not_paused(
        follow_run, database, quick):
    await db.update_sending_account(database, follow_run["account"]["id"], companion_device=None)
    await _worker().process_one(follow_run["settings"])
    account = await db.get_sending_account(database, follow_run["account"]["id"])
    assert account["status"] != ACCOUNT_PAUSED
    assert "no phone has linked it" in (account["last_error"] or "")
    assert await _tasks(database) == []


async def test_a_phone_cannot_report_an_unknown_result(database):
    with pytest.raises(ValueError):
        await companion.finish(database, 1, PHONE, "hacked", None, None)


# --- the API -------------------------------------------------------------------

@pytest.fixture
async def client(database, user):
    app = FastAPI()
    app.include_router(outreach_router.build_router(_stub_current_user, _stub_admin_required))
    _as(user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    CURRENT_USER.clear()


async def test_linking_a_phone_and_asking_for_work(client, account_factory, database):
    account = await account_factory(name="Lancastar")
    linked = await client.post("/api/outreach/companion/link", json={
        "device_id": PHONE, "account_id": account["id"], "handle": "@_lancastarmoon"})
    assert linked.status_code == 200, linked.text
    row = await db.get_sending_account(database, account["id"])
    assert row["companion_device"] == PHONE and row["device_handle"] == "_lancastarmoon"

    listed = (await client.get("/api/outreach/companion/accounts",
                               params={"device_id": PHONE})).json()
    assert [(a["name"], a["linked"]) for a in listed] == [("Lancastar", "this")]
    assert (await client.get("/api/outreach/companion/accounts",
                             params={"device_id": OTHER_PHONE})).json()[0]["linked"] == "other"

    nothing = await client.post("/api/outreach/companion/next", json={"device_id": PHONE})
    assert nothing.json() == {"task": None}
    row = await db.get_sending_account(database, account["id"])
    assert row["companion_seen_at"] is not None


async def test_switching_to_phone_needs_the_tiktok_username(client, account_factory, database):
    account = await account_factory(name="Lancastar")
    url = f"/api/outreach/accounts/{account['id']}"
    refused = await client.put(url, json={"via": "phone"})
    assert refused.status_code == 400
    ok = await client.put(url, json={"via": "phone", "device_handle": "@_lancastarmoon"})
    assert ok.status_code == 200, ok.text
    row = await db.get_sending_account(database, account["id"])
    assert row["via"] == "phone" and row["device_handle"] == "_lancastarmoon"
    back = await client.put(url, json={"via": "browser"})
    assert back.status_code == 200
    assert (await db.get_sending_account(database, account["id"]))["via"] == "browser"


async def test_only_tiktok_switches_to_phone(client, account_factory):
    account = await account_factory(name="IG", platform="instagram")
    response = await client.put(f"/api/outreach/accounts/{account['id']}",
                                json={"via": "phone", "device_handle": "someone"})
    assert response.status_code == 400


async def test_an_image_campaign_with_only_phone_accounts_says_why_it_cannot_start(
        client, account_factory, database):
    account = await account_factory(name="Lancastar")
    await db.update_sending_account(database, account["id"], via="phone", device_handle="x")
    campaign = (await client.post("/api/outreach/campaigns", json={
        "name": "C", "message_template": "Hi {{username}}"})).json()
    await db.update_outreach_campaign(database, campaign["id"], attachment_path="/tmp/p.png")
    await client.post(f"/api/outreach/campaigns/{campaign['id']}/import-text",
                      json={"content": "username\nalice\n"})
    response = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    errors = response.json()["detail"]["errors"]
    assert any("Phone accounts can't send images yet" in e for e in errors)


async def test_linking_switches_the_account_to_phone(client, account_factory, database):
    account = await account_factory(name="Lancastar")
    await client.post("/api/outreach/companion/link", json={
        "device_id": PHONE, "account_id": account["id"], "handle": "lancastar"})
    assert (await db.get_sending_account(database, account["id"]))["via"] == "phone"


async def test_only_tiktok_accounts_link(client, account_factory):
    account = await account_factory(name="IG", platform="instagram")
    response = await client.post("/api/outreach/companion/link", json={
        "device_id": PHONE, "account_id": account["id"], "handle": "someone"})
    assert response.status_code == 400


async def test_someone_elses_account_cannot_be_linked(client, account_factory, database):
    from services.auth import hash_password
    existing = await db.get_user_by_email(database, "other-phone@example.com")
    other_id = existing["id"] if existing else await db.create_user(
        database, "other-phone@example.com", hash_password("x" * 12), "Other")
    theirs = await db.create_sending_account(
        database, user_id=other_id, name="Theirs", platform="tiktok", status="idle", enabled=True)
    response = await client.post("/api/outreach/companion/link", json={
        "device_id": PHONE, "account_id": theirs, "handle": "someone"})
    assert response.status_code == 403


async def test_the_result_endpoint_refuses_unknown_results_and_strangers(
        client, follow_run, database, quick):
    worker = asyncio.create_task(_worker().process_one(follow_run["settings"]))
    try:
        task = None
        for _ in range(50):
            task = (await client.post("/api/outreach/companion/next",
                                      json={"device_id": PHONE})).json()["task"]
            if task:
                break
            await asyncio.sleep(0.02)
        assert task is not None
        url = f"/api/outreach/companion/tasks/{task['id']}/result"
        bad = await client.post(url, json={"device_id": PHONE, "status": "made_up"})
        assert bad.status_code == 400
        wrong = await client.post(url, json={"device_id": OTHER_PHONE, "status": RESULT_SENT})
        assert wrong.status_code == 409
        ok = await client.post(url, json={"device_id": PHONE, "status": RESULT_SENT})
        assert ok.status_code == 200
        again = await client.post(url, json={"device_id": PHONE, "status": RESULT_SENT})
        assert again.status_code == 409
    finally:
        await worker


async def test_a_malformed_phone_id_is_refused(client):
    response = await client.post("/api/outreach/companion/next", json={"device_id": "x"})
    assert response.status_code == 400


async def test_device_unavailable_is_a_result_the_phone_may_send():
    assert RESULT_DEVICE_UNAVAILABLE in companion.PHONE_RESULTS


async def test_a_message_the_phone_never_reports_is_not_sent_twice(message_run, database, quick):
    """Claimed, then silence: it may have gone out, so it is not retried."""
    from services.outreach.constants import JOB_FAILED
    async def claim_and_vanish():
        conn = await db.get_db()
        try:
            for _ in range(100):
                if await companion.claim(conn, PHONE, None):
                    return
                await asyncio.sleep(0.02)
        finally:
            await conn.close()
    await asyncio.gather(_worker().process_one(message_run["settings"]), claim_and_vanish())

    jobs = [dict(j) for j in await db.get_outreach_jobs(database, campaign_id=message_run["campaign"]["id"])]
    [gone] = [j for j in jobs if j["result_status"] == "outcome_unknown"]
    assert gone["status"] == JOB_FAILED  # not back on the queue


async def test_a_phone_account_unfollows_its_own_follows_through_the_phone(
        follow_run, database, quick, campaign_factory):
    """Followed through the phone, then unfollowed through it — in order."""
    await asyncio.gather(_worker().process_one(follow_run["settings"]), _phone(PHONE, RESULT_SENT))
    followed = [t["username"] for t in await db.get_outreach_targets(database, follow_run["campaign"]["id"])
                if t["status"] == TARGET_SENT]
    assert len(followed) == 1

    from services.outreach import importer, queue as job_queue
    await db.update_outreach_campaign(database, follow_run["campaign"]["id"], status="completed")
    unfollow = await campaign_factory(name="undo", message="", activity="unfollow")
    await importer.import_targets(database, unfollow["id"], f"username,profile_url\n{followed[0]},\n")
    await job_queue.start_campaign(database, unfollow, follow_run["settings"])
    await database.session.execute(text("UPDATE outreach_sending_accounts SET last_activity_at = NULL"))
    await database.session.commit()

    worked, task = await asyncio.gather(_worker().process_one(follow_run["settings"]), _phone(PHONE, RESULT_SENT))
    assert worked is True
    assert task["action"] == "unfollow" and task["username"] == followed[0]
    targets = await db.get_outreach_targets(database, unfollow["id"])
    assert [t["status"] for t in targets] == [TARGET_SENT]
