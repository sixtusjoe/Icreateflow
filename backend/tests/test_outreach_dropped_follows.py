"""One dropped follow is that person; three in a row is TikTok's limit.

2026-09-28: 8 dropped follows among ~150 that stuck, the same profiles
dropping again on retry — and every single drop paused the campaign for
six hours.
"""
from __future__ import annotations

from sqlalchemy import text

import database as db
from services.outreach import importer, queue as job_queue, runner
from services.outreach.browser import MessageResult
from services.outreach.browser.mock import MockMessenger
from services.outreach.constants import (
    CAMPAIGN_PAUSED,
    CAMPAIGN_RUNNING,
    JOB_QUEUED,
    RESULT_FOLLOW_DISCARDED,
)


class _Drops(MockMessenger):
    """Follows everyone, except that TikTok drops the follows to `dropped`."""

    def __init__(self, dropped: set[str]):
        super().__init__()
        self._dropped = dropped

    async def follow_target(self, account, target):
        self.followed.append((int(account.get("id") or 0), target["username"]))
        if target["username"] in self._dropped:
            return MessageResult.failure(
                RESULT_FOLLOW_DISCARDED, f"@{target['username']} showed Following, then Follow")
        return MessageResult.sent()


async def _campaign(database, campaign_factory, account_factory, settings, names):
    account = await account_factory()
    campaign = await campaign_factory(name="follows", message="", activity="follow")
    await importer.import_targets(
        database, campaign["id"], "username,profile_url\n" + "".join(f"{n},\n" for n in names))
    await db.assign_account_to_campaign(database, campaign["id"], account["id"])
    await job_queue.start_campaign(database, campaign, settings)
    return campaign


async def _drain(database, driver, settings, times: int) -> None:
    for _ in range(times):
        # Only the account's pacing is cleared: a dropped person's retry
        # keeps its real wait, as it does in a run.
        await database.session.execute(text("UPDATE outreach_sending_accounts SET last_activity_at = NULL"))
        await database.session.commit()
        await runner.OutreachWorker(worker_id="t", driver=driver, once=True).process_one(settings)


async def _job(database, campaign_id, username) -> dict:
    return dict((await database.session.execute(text(
        "SELECT j.* FROM outreach_jobs j JOIN outreach_targets t ON t.id = j.target_id "
        " WHERE j.campaign_id = :c AND t.username = :u ORDER BY j.id DESC LIMIT 1"
    ), {"c": campaign_id, "u": username})).mappings().first())


async def test_one_dropped_follow_retries_that_person_and_carries_on(
        database, campaign_factory, account_factory, settings):
    campaign = await _campaign(database, campaign_factory, account_factory, settings,
                               ["kept_one", "dropper", "kept_two"])
    driver = _Drops({"dropper"})
    await _drain(database, driver, settings, 3)

    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING and not row.get("paused_reason")
    assert [u for _, u in driver.followed] == ["kept_one", "dropper", "kept_two"]
    job = await _job(database, campaign["id"], "dropper")
    assert job["status"] == JOB_QUEUED and job["result_status"] == RESULT_FOLLOW_DISCARDED
    assert int(job["attempts"]) == 1  # spent: a profile always dropped is left behind in the end


async def test_three_drops_in_a_row_is_the_limit(
        database, campaign_factory, account_factory, settings):
    names = ["dropper_one", "dropper_two", "dropper_three", "waiting"]
    campaign = await _campaign(database, campaign_factory, account_factory, settings, names)
    await _drain(database, _Drops(set(names[:3])), settings, 3)

    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_PAUSED
    assert "dropper_three" in (row.get("paused_reason") or "")


async def test_a_kept_follow_between_drops_resets_the_count(
        database, campaign_factory, account_factory, settings):
    names = ["dropper_one", "dropper_two", "kept_one", "dropper_three", "dropper_four"]
    campaign = await _campaign(database, campaign_factory, account_factory, settings, names)
    await _drain(database, _Drops({"dropper_one", "dropper_two", "dropper_three", "dropper_four"}),
                 settings, 5)

    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING
