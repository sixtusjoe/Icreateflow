"""An unfollow campaign undoes only ICREATEFLOW's own follows.

The operator's rule (2026-09-27): unfollow only the people a follow
campaign actually followed ("Followed" on the campaign page — a follow job
that succeeded with `sent`). A friend, a follow made by hand, a profile
that was already followed or only requested: left alone, nothing pressed.
"""
from __future__ import annotations

from sqlalchemy import text

import database as db
from services.outreach import importer, queue as job_queue, runner
from services.outreach.browser.mock import MockMessenger
from services.outreach.constants import (
    JOB_QUEUED,
    RESULT_ALREADY_FOLLOWING,
    RESULT_FOLLOW_REQUESTED,
    RESULT_NOT_OUR_FOLLOW,
    TARGET_SENT,
    TARGET_SKIPPED,
)


async def _run(driver, settings) -> bool:
    return await runner.OutreachWorker(worker_id="t", driver=driver, once=True).process_one(settings)


async def _clear_waits(database) -> None:
    await database.session.execute(text("UPDATE outreach_jobs SET run_after = NULL"))
    await database.session.execute(text("UPDATE outreach_sending_accounts SET last_activity_at = NULL"))
    await database.session.commit()


async def _campaign(database, campaign_factory, settings, activity: str, names: list[str],
                    accounts: list[dict] | None = None) -> dict:
    campaign = await campaign_factory(name=f"{activity} run", message="", activity=activity)
    await importer.import_targets(
        database, campaign["id"], "username,profile_url\n" + "".join(f"{n},\n" for n in names))
    for a in accounts or []:
        await db.assign_account_to_campaign(database, campaign["id"], a["id"])
    await job_queue.start_campaign(database, campaign, settings)
    return dict(await db.get_outreach_campaign(database, campaign["id"]))


async def _drain(database, driver, settings, times: int) -> None:
    for _ in range(times):
        await _clear_waits(database)
        await _run(driver, settings)


async def _status(database, campaign_id: int, username: str) -> dict:
    return next(dict(t) for t in await db.get_outreach_targets(database, campaign_id)
                if t["username"] == username)


async def test_only_people_a_follow_campaign_followed_are_unfollowed(
        database, campaign_factory, account_factory, settings):
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow", ["ours"], [account])
    await _drain(database, MockMessenger(), settings, 1)
    await db.update_outreach_campaign(database, follows["id"], status="completed")

    unfollow = await _campaign(database, campaign_factory, settings, "unfollow",
                               ["ours", "friend"], [account])
    driver = MockMessenger()
    await _drain(database, driver, settings, 2)

    assert [u for _, u in driver.unfollowed] == ["ours"]
    assert (await _status(database, unfollow["id"], "ours"))["status"] == TARGET_SENT
    friend = await _status(database, unfollow["id"], "friend")
    assert friend["status"] == TARGET_SKIPPED
    assert "left alone" in friend["error_message"]


async def test_already_following_is_not_ours_to_undo(
        database, campaign_factory, account_factory, settings):
    """Followed before the campaign got there: not ICREATEFLOW's to undo."""
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow", ["mine_before"], [account])
    await _drain(database, _AlreadyFollowing(), settings, 1)
    await db.update_outreach_campaign(database, follows["id"], status="completed")

    unfollow = await _campaign(database, campaign_factory, settings, "unfollow", ["mine_before"], [account])
    driver = MockMessenger()
    await _drain(database, driver, settings, 1)
    assert driver.unfollowed == []
    assert (await _status(database, unfollow["id"], "mine_before"))["status"] == TARGET_SKIPPED


async def test_the_account_that_followed_them_does_the_unfollow(
        database, campaign_factory, account_factory, settings):
    """Two accounts on the campaign: the other one waits, nobody is charged."""
    a = await account_factory(name="A")
    b = await account_factory(name="B")
    follows = await _campaign(database, campaign_factory, settings, "follow", ["xavier"], [a])
    await _drain(database, MockMessenger(), settings, 1)
    await db.update_outreach_campaign(database, follows["id"], status="completed")

    unfollow = await _campaign(database, campaign_factory, settings, "unfollow", ["xavier"], [a, b])
    # B is leased first: make A the more recently active of the two.
    await database.session.execute(text(
        "UPDATE outreach_sending_accounts SET last_activity_at = "
        "(NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day' WHERE id = :b"), {"b": b["id"]})
    await database.session.execute(text(
        "UPDATE outreach_sending_accounts SET last_activity_at = "
        "(NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour' WHERE id = :a"), {"a": a["id"]})
    await database.session.commit()
    driver = MockMessenger()
    await _run(driver, settings)
    assert driver.unfollowed == []  # B didn't follow them
    [job] = [dict(j) for j in await db.get_outreach_jobs(database, campaign_id=unfollow["id"])]
    assert job["status"] == JOB_QUEUED and job["result_status"] == RESULT_NOT_OUR_FOLLOW
    assert int(job["attempts"] or 0) == 0  # held, not charged

    # Now A gets it.
    await database.session.execute(text(
        "UPDATE outreach_sending_accounts SET last_activity_at = "
        "(NOW() AT TIME ZONE 'UTC') - INTERVAL '2 days' WHERE id = :a"), {"a": a["id"]})
    await database.session.execute(text("UPDATE outreach_jobs SET run_after = NULL"))
    await database.session.commit()
    await _run(driver, settings)
    assert driver.unfollowed == [(a["id"], "xavier")]


class _AlreadyFollowing(MockMessenger):
    async def follow_target(self, account, target):
        from services.outreach.browser import MessageResult
        self.followed.append((int(account.get("id") or 0), target["username"]))
        return MessageResult.done(RESULT_ALREADY_FOLLOWING)


# --- "Unfollow everyone it followed" -------------------------------------------

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from routers import outreach as outreach_router  # noqa: E402
from tests.test_outreach_api import CURRENT_USER, _as, _stub_admin_required, _stub_current_user  # noqa: E402


@pytest.fixture
async def client(database, user):
    app = FastAPI()
    app.include_router(outreach_router.build_router(_stub_current_user, _stub_admin_required))
    _as(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    CURRENT_USER.clear()


async def test_one_click_makes_an_unfollow_campaign_of_exactly_the_followed(
        client, database, campaign_factory, account_factory, settings):
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow",
                              ["followed_one", "was_already", "followed_two"], [account])
    driver = _Mixed({"was_already"})
    await _drain(database, driver, settings, 3)

    response = await client.post(f"/api/outreach/campaigns/{follows['id']}/unfollow-followed")
    assert response.status_code == 200, response.text
    body = response.json()
    new = body["campaign"]
    assert new["activity"] == "unfollow" and new["status"] == "draft"
    names = sorted(t["username"] for t in await db.get_outreach_targets(database, new["id"]))
    assert names == ["followed_one", "followed_two"]
    assert await db.get_campaign_account_ids(database, new["id"]) == [account["id"]]


async def test_only_a_follow_campaign_can_be_unfollowed(client, campaign_factory):
    messages = await campaign_factory(name="msgs")
    response = await client.post(f"/api/outreach/campaigns/{messages['id']}/unfollow-followed")
    assert response.status_code == 400


class _Mixed(MockMessenger):
    """Follows everyone except `already`, which reports already_following."""

    def __init__(self, already: set[str]):
        super().__init__()
        self._already = already

    async def follow_target(self, account, target):
        from services.outreach.browser import MessageResult
        self.followed.append((int(account.get("id") or 0), target["username"]))
        if target["username"] in self._already:
            return MessageResult.done(RESULT_ALREADY_FOLLOWING)
        return MessageResult.sent()


async def test_the_first_followed_is_the_first_unfollowed(
        client, database, campaign_factory, account_factory, settings):
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow",
                              ["bravo", "alpha", "charlie"], [account])
    await _drain(database, MockMessenger(), settings, 3)
    # Followed in this order: charlie, then alpha, then bravo.
    for name, minutes_ago in (("charlie", 30), ("alpha", 20), ("bravo", 10)):
        await database.session.execute(text(
            "UPDATE outreach_jobs j SET completed_at = (NOW() AT TIME ZONE 'UTC') - "
            "  (:m * INTERVAL '1 minute') FROM outreach_targets t "
            " WHERE t.id = j.target_id AND t.username = :u AND t.campaign_id = :c"),
            {"m": minutes_ago, "u": name, "c": follows["id"]})
    await database.session.commit()

    made = (await client.post(f"/api/outreach/campaigns/{follows['id']}/unfollow-followed")).json()
    await client.post(f"/api/outreach/campaigns/{made['campaign']['id']}/start")
    driver = MockMessenger()
    await _drain(database, driver, settings, 3)
    assert [u for _, u in driver.unfollowed] == ["charlie", "alpha", "bravo"]


async def test_clicking_again_adds_only_the_newly_followed_to_the_same_campaign(
        client, database, campaign_factory, account_factory, settings):
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow",
                              ["first_one", "second_one"], [account])
    await _drain(database, MockMessenger(), settings, 2)

    made = (await client.post(f"/api/outreach/campaigns/{follows['id']}/unfollow-followed")).json()
    assert made["created"] is True and made["people"] == 2
    unfollow_id = made["campaign"]["id"]

    # More people followed on the same follow campaign later.
    await importer.import_targets(database, follows["id"], "username,profile_url\nthird_one,\n")
    await job_queue.start_campaign(
        database, dict(await db.get_outreach_campaign(database, follows["id"])), settings)
    await _drain(database, MockMessenger(), settings, 1)

    again = (await client.post(f"/api/outreach/campaigns/{follows['id']}/unfollow-followed")).json()
    assert again["created"] is False
    assert again["campaign"]["id"] == unfollow_id  # the same campaign, not another
    assert again["people"] == 1  # only the new one
    names = [t["username"] for t in sorted(
        await db.get_outreach_targets(database, unfollow_id), key=lambda t: t["id"])]
    assert names == ["first_one", "second_one", "third_one"]

    # Nothing new: nothing added, still the same campaign.
    third = (await client.post(f"/api/outreach/campaigns/{follows['id']}/unfollow-followed")).json()
    assert third["created"] is False and third["people"] == 0


async def test_a_follow_campaign_that_has_followed_cannot_be_switched_to_unfollow(
        client, database, campaign_factory, account_factory, settings):
    """Switching it ran the not-yet-followed half of the list as unfollows
    (2026-09-28) — the followed half is what "Unfollow everyone it followed"
    is for."""
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow",
                              ["done_one", "waiting"], [account])
    await _drain(database, MockMessenger(), settings, 1)
    await job_queue.pause_campaign(database, follows["id"])

    response = await client.put(f"/api/outreach/campaigns/{follows['id']}",
                                  json={"activity": "unfollow"})
    assert response.status_code == 400
    assert "Unfollow everyone it followed" in response.json()["detail"]
    assert (await db.get_outreach_campaign(database, follows["id"]))["activity"] == "follow"


async def test_a_campaign_nobody_was_worked_on_can_still_change_activity(
        client, campaign_factory):
    draft = await campaign_factory(name="draft", message="", activity="follow")
    response = await client.put(f"/api/outreach/campaigns/{draft['id']}",
                                  json={"activity": "unfollow"})
    assert response.status_code == 200, response.text
    assert response.json()["activity"] == "unfollow"


class _Requested(MockMessenger):
    """Every follow lands as a request to a private account."""

    async def follow_target(self, account, target):
        from services.outreach.browser import MessageResult
        self.followed.append((int(account.get("id") or 0), target["username"]))
        return MessageResult.done(RESULT_FOLLOW_REQUESTED)


async def test_a_request_the_campaign_sent_is_undone(
        database, campaign_factory, account_factory, settings):
    """Accepted, it's a follow; still waiting, it's withdrawn — either way
    it was ICREATEFLOW's (the operator's choice, 2026-09-28)."""
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow", ["private_one"], [account])
    await _drain(database, _Requested(), settings, 1)
    await db.update_outreach_campaign(database, follows["id"], status="completed")

    unfollow = await _campaign(database, campaign_factory, settings, "unfollow", ["private_one"], [account])
    driver = MockMessenger()
    await _drain(database, driver, settings, 1)
    assert [u for _, u in driver.unfollowed] == ["private_one"]
    assert (await _status(database, unfollow["id"], "private_one"))["status"] == TARGET_SENT


async def test_the_one_click_list_includes_requests_but_not_already_following(
        client, database, campaign_factory, account_factory, settings):
    account = await account_factory()
    follows = await _campaign(database, campaign_factory, settings, "follow",
                              ["followed", "requested", "was_already"], [account])

    class Each(MockMessenger):
        async def follow_target(self, account, target):
            from services.outreach.browser import MessageResult
            name = target["username"]
            if name == "requested":
                return MessageResult.done(RESULT_FOLLOW_REQUESTED)
            if name == "was_already":
                return MessageResult.done(RESULT_ALREADY_FOLLOWING)
            return MessageResult.sent()

    await _drain(database, Each(), settings, 3)
    response = await client.post(f"/api/outreach/campaigns/{follows['id']}/unfollow-followed")
    assert response.status_code == 200, response.text
    new = response.json()["campaign"]
    names = sorted(t["username"] for t in await db.get_outreach_targets(database, new["id"]))
    assert names == ["followed", "requested"]
