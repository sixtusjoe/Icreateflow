"""A running campaign never just sits there.

Two ways campaign 15 stopped moving with people left, both silent
(2026-09-28): Stop stranded people whose job was waiting to retry, and the
campaign's job limit left 19 people with no job and no word.
"""
from __future__ import annotations

from sqlalchemy import text

import database as db
from services.outreach import importer, queue as job_queue, runner
from services.outreach.browser.mock import MockMessenger
from services.outreach.constants import (
    CAMPAIGN_PAUSED,
    CAMPAIGN_RUNNING,
    JOB_QUEUED,
    TARGET_PAUSED,
    TARGET_PROCESSING,
    TARGET_QUEUED,
)


async def _campaign(database, campaign_factory, account_factory, settings, names):
    account = await account_factory()
    campaign = await campaign_factory(name="follows", message="", activity="follow")
    await importer.import_targets(
        database, campaign["id"], "username,profile_url\n" + "".join(f"{n},\n" for n in names))
    await db.assign_account_to_campaign(database, campaign["id"], account["id"])
    await job_queue.start_campaign(database, campaign, settings)
    return dict(await db.get_outreach_campaign(database, campaign["id"]))


async def _targets(database, campaign_id) -> dict[str, str]:
    return {t["username"]: t["status"] for t in await db.get_outreach_targets(database, campaign_id)}


async def _live_jobs(database, campaign_id) -> int:
    return (await database.session.execute(text(
        "SELECT COUNT(*) FROM outreach_jobs WHERE campaign_id = :c AND status IN ('queued','processing')"
    ), {"c": campaign_id})).scalar_one()


async def _waiting_to_retry(database, campaign_id, username) -> None:
    """What a held or retried job looks like: job queued, target `processing`."""
    await database.session.execute(text(
        "UPDATE outreach_targets SET status = :p WHERE campaign_id = :c AND username = :u"
    ), {"p": TARGET_PROCESSING, "c": campaign_id, "u": username})
    await database.session.commit()


async def test_stop_releases_people_waiting_to_retry(
        database, campaign_factory, account_factory, settings):
    campaign = await _campaign(database, campaign_factory, account_factory, settings, ["retrying", "fresh"])
    await _waiting_to_retry(database, campaign["id"], "retrying")

    await job_queue.stop_campaign(database, campaign["id"])
    assert await _targets(database, campaign["id"]) == {"retrying": TARGET_PAUSED, "fresh": TARGET_PAUSED}

    await job_queue.start_campaign(database, campaign, settings)
    assert await _live_jobs(database, campaign["id"]) == 2


async def test_start_picks_up_people_an_old_stop_stranded(
        database, campaign_factory, account_factory, settings):
    campaign = await _campaign(database, campaign_factory, account_factory, settings, ["stranded"])
    # How the old Stop left them: job cancelled, target still `processing`.
    await database.session.execute(text(
        "UPDATE outreach_jobs SET status = 'cancelled' WHERE campaign_id = :c"), {"c": campaign["id"]})
    await database.session.commit()
    await _waiting_to_retry(database, campaign["id"], "stranded")
    await db.update_outreach_campaign(database, campaign["id"], status=CAMPAIGN_PAUSED)

    await job_queue.start_campaign(database, campaign, settings)
    assert await _targets(database, campaign["id"]) == {"stranded": TARGET_QUEUED}
    assert await _live_jobs(database, campaign["id"]) == 1


async def test_a_campaign_at_its_job_limit_pauses_and_says_so(
        database, campaign_factory, account_factory, settings):
    campaign = await _campaign(database, campaign_factory, account_factory, settings, ["first"])
    await db.update_outreach_campaign(database, campaign["id"], max_jobs=1)
    await importer.import_targets(database, campaign["id"], "username,profile_url\nsecond,\n")
    await runner.OutreachWorker(worker_id="t", driver=MockMessenger(), once=True).process_one(settings)
    assert await _live_jobs(database, campaign["id"]) == 0

    await runner.unstick(database, settings)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_PAUSED
    assert "limit of 1 jobs, with 1 person still to go" in row["paused_reason"]
    assert "Maximum jobs per campaign" in row["paused_reason"]


async def test_a_raised_limit_gets_a_stalled_campaign_moving(
        database, campaign_factory, account_factory, settings):
    campaign = await _campaign(database, campaign_factory, account_factory, settings, ["first"])
    await db.update_outreach_campaign(database, campaign["id"], max_jobs=1)
    await importer.import_targets(database, campaign["id"], "username,profile_url\nsecond,\n")
    await runner.OutreachWorker(worker_id="t", driver=MockMessenger(), once=True).process_one(settings)
    await db.update_outreach_campaign(database, campaign["id"], max_jobs=5)

    await runner.unstick(database, settings)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING
    assert await _live_jobs(database, campaign["id"]) == 1


async def test_a_campaign_with_work_queued_is_left_alone(
        database, campaign_factory, account_factory, settings):
    campaign = await _campaign(database, campaign_factory, account_factory, settings, ["alice", "bruno"])
    await runner.unstick(database, settings)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING and not row.get("paused_reason")
    assert await _live_jobs(database, campaign["id"]) == 2


async def test_an_account_out_of_jobs_pauses_the_campaign_and_says_why(
        database, campaign_factory, account_factory, settings):
    """Lancastar at 1000 of 1000 (2026-09-28): work queued, "running", and
    only the server log knew why."""
    account = await account_factory(name="Lancastar")
    campaign = await campaign_factory(name="follows", message="", activity="follow",
                                      max_jobs_per_account=1)
    await importer.import_targets(database, campaign["id"], "username,profile_url\nalice,\nbruno,\n")
    await db.assign_account_to_campaign(database, campaign["id"], account["id"])
    await job_queue.start_campaign(database, campaign, settings)
    worker = runner.OutreachWorker(worker_id="t", driver=MockMessenger(), once=True)
    await worker.process_one(settings)
    await database.session.execute(text("UPDATE outreach_sending_accounts SET last_activity_at = NULL"))
    await database.session.commit()

    await worker.process_one(settings)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_PAUSED
    assert "Lancastar has done 1 of its 1 jobs" in row["paused_reason"]
    assert "Maximum jobs per account (per campaign)" in row["paused_reason"]


async def test_a_busy_account_does_not_pause_the_campaign(
        database, campaign_factory, account_factory, settings):
    """Inside its send interval: it clears by itself, so nothing is said."""
    campaign = await _campaign(database, campaign_factory, account_factory, settings,
                               ["alice", "bruno"])
    await database.session.execute(text(
        "UPDATE outreach_sending_accounts SET last_activity_at = (NOW() AT TIME ZONE 'UTC')"))
    await database.session.commit()
    settings = {**settings, "outreach_min_send_interval_seconds": 3600}
    worker = runner.OutreachWorker(worker_id="t", driver=MockMessenger(), once=True)
    await worker.process_one(settings)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING and not row.get("paused_reason")


class _Frozen(MockMessenger):
    """A browser that never comes back from a follow."""

    def __init__(self):
        super().__init__()
        self.released: list[int] = []

    async def follow_target(self, account, target):
        import asyncio
        await asyncio.sleep(3600)

    async def release_account(self, account_id):
        self.released.append(int(account_id))


async def test_a_frozen_browser_gives_the_person_back_and_resets_its_tab(
        database, campaign_factory, account_factory, settings, monkeypatch):
    """@_giuliosss, 2026-09-28: one frozen follow held the account for
    fourteen minutes, and with it every campaign that account serves."""
    monkeypatch.setattr(runner, "BROWSER_ACTION_SECONDS", 1)
    campaign = await _campaign(database, campaign_factory, account_factory, settings, ["alice"])
    driver = _Frozen()
    await runner.OutreachWorker(worker_id="t", driver=driver, once=True).process_one(settings)

    job = dict((await database.session.execute(text(
        "SELECT * FROM outreach_jobs WHERE campaign_id = :c"), {"c": campaign["id"]})).mappings().first())
    assert job["status"] == JOB_QUEUED  # back for another try
    assert "stopped responding" in job["error_message"]
    assert driver.released, "the frozen tab has to be replaced"
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING
