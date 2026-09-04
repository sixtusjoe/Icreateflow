"""The worker end to end, driven by the mock messenger.

Nothing here opens a browser or contacts a platform: every send goes
through `MockMessenger`, which records what it was asked to send and
returns whatever outcome the test scripts.
"""
from __future__ import annotations

from sqlalchemy import text

import database as db
from services.outreach import accounts as account_mgr, importer, queue as job_queue, runner
from services.outreach.browser.mock import MockMessenger
from services.outreach.constants import (
    ACCOUNT_PAUSED,
    CAMPAIGN_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_SUCCEEDED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_SESSION_EXPIRED,
    TARGET_FAILED,
    TARGET_SENT,
    TARGET_SKIPPED,
)


async def _run(driver, settings, worker_id: str = "test-worker") -> bool:
    worker = runner.OutreachWorker(worker_id=worker_id, driver=driver, once=True)
    return await worker.process_one(settings)


async def _clear_backoff(database) -> None:
    await database.session.execute(text("UPDATE outreach_jobs SET run_after = NULL"))
    await database.session.commit()


# --- the happy path --------------------------------------------------------

async def test_worker_sends_and_records_a_success(seeded, database):
    driver = MockMessenger()
    assert await _run(driver, seeded["settings"]) is True

    assert len(driver.sent) == 1
    account_id, username, message = driver.sent[0]
    assert account_id == seeded["account"]["id"]
    assert message == f"Hello {username}, quick question."

    target = next(
        t for t in await db.get_outreach_targets(database, seeded["campaign"]["id"])
        if t["username"] == username
    )
    assert target["status"] == TARGET_SENT
    account = dict(await db.get_sending_account(database, account_id))
    assert account["messages_processed"] == 1
    assert account["status"] != ACCOUNT_PAUSED


async def test_the_message_is_rendered_per_target(seeded, database):
    driver = MockMessenger()
    settings = seeded["settings"]
    for _ in range(3):
        await _run(driver, settings)

    sent = {username: message for _, username, message in driver.sent}
    assert sent == {
        "alice": "Hello alice, quick question.",
        "bob": "Hello bob, quick question.",
        "carol": "Hello carol, quick question.",
    }


async def test_a_full_campaign_drains_and_completes(seeded, database):
    driver = MockMessenger()
    settings = seeded["settings"]
    while await _run(driver, settings):
        pass

    campaign = dict(await db.get_outreach_campaign(database, seeded["campaign"]["id"]))
    assert campaign["status"] == CAMPAIGN_COMPLETED
    assert campaign["successful_count"] == 3
    assert campaign["processed_count"] == 3
    counts = await job_queue.job_counts(database, campaign["id"])
    assert counts == {JOB_SUCCEEDED: 3}


async def test_each_target_is_messaged_exactly_once(seeded, database):
    driver = MockMessenger()
    settings = seeded["settings"]
    while await _run(driver, settings):
        pass
    usernames = [username for _, username, _ in driver.sent]
    assert sorted(usernames) == ["alice", "bob", "carol"]
    assert len(usernames) == len(set(usernames))


# --- failure handling ------------------------------------------------------

async def test_a_driver_failure_is_recorded_and_retried(seeded, database):
    driver = MockMessenger(outcomes=[(RESULT_NAVIGATION_TIMEOUT, "timed out")])
    settings = seeded["settings"]
    await _run(driver, settings)

    job = (await db.get_outreach_jobs(database, campaign_id=seeded["campaign"]["id"]))[-1]
    assert dict(job)["status"] == JOB_QUEUED         # requeued for another go
    assert dict(job)["result_status"] == RESULT_NAVIGATION_TIMEOUT
    assert dict(job)["error_message"] == "timed out"

    # Second attempt succeeds and clears the error.
    await _clear_backoff(database)
    await _run(driver, settings)
    target = dict(await db.get_outreach_target(database, dict(job)["target_id"]))
    assert target["status"] == TARGET_SENT


async def test_a_closed_inbox_skips_the_target_without_retrying(seeded, database):
    driver = MockMessenger(outcomes=[(RESULT_MESSAGING_UNAVAILABLE, "DMs closed")])
    await _run(driver, seeded["settings"])

    jobs = [dict(j) for j in await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"]
    )]
    failed = [j for j in jobs if j["status"] == JOB_FAILED]
    assert len(failed) == 1
    target = dict(await db.get_outreach_target(database, failed[0]["target_id"]))
    assert target["status"] == TARGET_SKIPPED
    # The account is not blamed for a target-side problem.
    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["consecutive_errors"] == 0


async def test_an_expired_session_pauses_the_account_and_stops_the_run(seeded, database):
    driver = MockMessenger(default=(RESULT_SESSION_EXPIRED, "login wall"))
    settings = seeded["settings"]
    assert await _run(driver, settings) is True

    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["status"] == ACCOUNT_PAUSED
    assert "session_expired" in account["paused_reason"]

    # With the only account paused there is nothing to run — and crucially
    # the worker does not spin claiming jobs it cannot send.
    await _clear_backoff(database)
    assert await _run(driver, settings) is False
    assert len(driver.sent) == 1


async def test_a_driver_that_raises_is_contained(seeded, database):
    def explode(account, target, message):
        raise RuntimeError("chromium vanished")

    driver = MockMessenger(handler=explode)
    settings = seeded["settings"]
    assert await _run(driver, settings) is True

    job = dict((await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"]
    ))[-1])
    assert job["status"] == JOB_QUEUED
    assert "chromium vanished" in (job["error_message"] or "")


async def test_a_driver_returning_junk_is_treated_as_a_failure(seeded, database):
    """A third-party driver that breaks the contract must not break the queue."""

    class BadDriver:
        name = "bad"

        async def startup(self):
            pass

        async def send_message(self, account, target, message):
            return {"success": True}          # not a MessageResult

        async def release_account(self, account_id):
            pass

        async def shutdown(self):
            pass

    assert await _run(BadDriver(), seeded["settings"]) is True
    job = dict((await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"]
    ))[-1])
    assert job["status"] == JOB_QUEUED
    assert "MessageResult" in (job["error_message"] or "")


async def test_an_unrenderable_template_fails_the_target_without_retrying(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory(message="Hi {{username}}, about {{offer}}")
    await account_factory()
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    await job_queue.start_campaign(database, campaign, settings)

    driver = MockMessenger()
    assert await _run(driver, settings) is True

    # Nothing was sent — the missing variable was caught before the driver.
    assert driver.sent == []
    target = dict((await db.get_outreach_targets(database, campaign["id"]))[0])
    assert target["status"] == TARGET_FAILED
    assert "offer" in target["error_message"]


async def test_campaign_variables_fill_the_template(
    database, campaign_factory, account_factory, settings
):
    from services.outreach import templates as template_svc

    campaign = await campaign_factory(
        message="Hi {{username}}, about {{offer}}",
        template_vars=template_svc.dump_vars({"offer": "our beta"}),
    )
    await account_factory()
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    await job_queue.start_campaign(database, campaign, settings)

    driver = MockMessenger()
    await _run(driver, settings)
    assert driver.sent[0][2] == "Hi alice, about our beta"


# --- concurrency and recovery ---------------------------------------------

async def test_two_workers_do_not_send_to_the_same_target(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    await account_factory(name="A")
    await account_factory(name="B")
    await importer.import_targets(database, campaign["id"], "username\nalice\nbob\n")
    await job_queue.start_campaign(database, campaign, settings)

    driver = MockMessenger()
    assert await _run(driver, settings, worker_id="worker-a") is True
    assert await _run(driver, settings, worker_id="worker-b") is True

    usernames = sorted(username for _, username, _ in driver.sent)
    assert usernames == ["alice", "bob"]


async def test_work_resumes_after_a_worker_crash(seeded, database):
    """Simulate SIGKILL mid-send: the job is left claimed, then reaped."""
    campaign, settings = seeded["campaign"], seeded["settings"]
    job = await job_queue.claim_job(
        database, campaign["id"], seeded["account"]["id"], "doomed", settings
    )
    await database.session.execute(
        text(
            "UPDATE outreach_jobs "
            "   SET lease_expires_at = (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour' "
            " WHERE id = :id"
        ),
        {"id": job["id"]},
    )
    await database.session.execute(
        text(
            "UPDATE outreach_sending_accounts "
            "   SET last_activity_at = (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour'"
        )
    )
    await database.session.commit()

    assert await job_queue.reap_stale_jobs(database, settings) == 1
    await account_mgr.release_expired_leases(database, settings)

    driver = MockMessenger()
    while await _run(driver, settings):
        pass

    campaign_row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert campaign_row["successful_count"] == 3
    assert campaign_row["status"] == CAMPAIGN_COMPLETED
    # The interrupted target was retried, not lost or double-sent.
    usernames = [username for _, username, _ in driver.sent]
    assert sorted(usernames) == ["alice", "bob", "carol"]


async def test_the_global_kill_switch_stops_the_worker(seeded, database):
    from services.outreach import config as cfg

    await db.set_site_config(database, cfg.WORKERS_ENABLED_KEY, "0")
    try:
        settings = await cfg.get_all(database)
        assert settings[cfg.WORKERS_ENABLED_KEY] is False
        driver = MockMessenger()
        worker = runner.OutreachWorker(driver=driver, once=True)
        await worker._slot()
        assert driver.sent == []
    finally:
        await db.set_site_config(database, cfg.WORKERS_ENABLED_KEY, "1")


async def test_run_once_helper_uses_the_supplied_driver(seeded, database):
    driver = MockMessenger()
    assert await runner.run_once(driver=driver) is True
    assert len(driver.sent) == 1
