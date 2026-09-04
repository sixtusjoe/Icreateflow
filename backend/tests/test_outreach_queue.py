"""Queue mechanics: enqueue, claim, exclusivity, retries, crash recovery."""
from __future__ import annotations

from sqlalchemy import text

import database as db
from services.outreach import importer, queue as job_queue, stats
from services.outreach.constants import (
    CAMPAIGN_COMPLETED,
    CAMPAIGN_PAUSED,
    CAMPAIGN_RUNNING,
    CAMPAIGN_STOPPED,
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_PROCESSING,
    JOB_QUEUED,
    JOB_SUCCEEDED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    TARGET_FAILED,
    TARGET_PAUSED,
    TARGET_QUEUED,
    TARGET_SENT,
    TARGET_SKIPPED,
)


async def _expire_lease(database, job_id: int) -> None:
    """Pretend the worker holding this job died some time ago."""
    await database.session.execute(
        text(
            "UPDATE outreach_jobs "
            "   SET lease_expires_at = (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour' "
            " WHERE id = :id"
        ),
        {"id": job_id},
    )
    await database.session.commit()


async def _clear_backoff(database, job_id: int) -> None:
    await database.session.execute(
        text("UPDATE outreach_jobs SET run_after = NULL WHERE id = :id"), {"id": job_id}
    )
    await database.session.commit()


# --- enqueue ---------------------------------------------------------------

async def test_start_enqueues_one_job_per_queued_target(seeded, database):
    campaign = seeded["campaign"]
    assert campaign["status"] == CAMPAIGN_RUNNING
    counts = await job_queue.job_counts(database, campaign["id"])
    assert counts == {JOB_QUEUED: 3}


async def test_starting_twice_does_not_duplicate_jobs(seeded, database):
    campaign, settings = seeded["campaign"], seeded["settings"]
    added = await job_queue.start_campaign(database, campaign, settings)
    assert added == 0
    assert await job_queue.job_counts(database, campaign["id"]) == {JOB_QUEUED: 3}


async def test_max_jobs_per_campaign_caps_the_queue(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory(max_jobs=2)
    await account_factory()
    await importer.import_targets(database, campaign["id"], "username\na1\na2\na3\na4\n")
    created = await job_queue.start_campaign(database, campaign, settings)
    assert created == 2


# --- claiming --------------------------------------------------------------

async def test_claim_marks_job_processing_and_target_processing(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "worker-a", settings
    )
    assert job["status"] == JOB_PROCESSING
    assert job["attempts"] == 1
    assert job["worker_id"] == "worker-a"
    assert job["lease_expires_at"] is not None

    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == "processing"
    assert target["assigned_account_id"] == account["id"]
    assert target["attempts"] == 1


async def test_two_workers_never_claim_the_same_job(seeded, database):
    """The core no-double-send guarantee."""
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    first = await job_queue.claim_job(
        database, campaign["id"], account["id"], "worker-a", settings
    )
    second_conn = await db.get_db()
    try:
        second = await job_queue.claim_job(
            second_conn, campaign["id"], account["id"], "worker-b", settings
        )
    finally:
        await second_conn.close()
    assert first["id"] != second["id"]
    assert first["target_id"] != second["target_id"]


async def test_a_target_cannot_have_two_live_jobs(seeded, database):
    """Even a hand-written insert is refused by the partial unique index."""
    from sqlalchemy.exc import IntegrityError
    import pytest

    campaign = seeded["campaign"]
    target = (await db.get_outreach_targets(database, campaign["id"]))[0]
    with pytest.raises(IntegrityError):
        await database.session.execute(
            text(
                "INSERT INTO outreach_jobs (campaign_id, target_id, status) "
                "VALUES (:c, :t, 'queued')"
            ),
            {"c": campaign["id"], "t": target["id"]},
        )
    await database.session.rollback()


async def test_paused_campaign_jobs_are_not_claimable(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    await job_queue.pause_campaign(database, campaign["id"])
    assert await job_queue.claim_job(
        database, campaign["id"], account["id"], "worker-a", settings
    ) is None
    assert await job_queue.runnable_campaign_ids(database) == []


async def test_a_job_behind_its_backoff_is_not_claimable(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    await database.session.execute(
        text(
            "UPDATE outreach_jobs "
            "   SET run_after = (NOW() AT TIME ZONE 'UTC') + INTERVAL '1 hour'"
        )
    )
    await database.session.commit()
    assert await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    ) is None


# --- results ---------------------------------------------------------------

async def test_success_marks_job_and_target_sent_and_updates_counters(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    await job_queue.complete_job(database, job)

    assert dict(await db.get_outreach_job(database, job["id"]))["status"] == JOB_SUCCEEDED
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_SENT
    assert target["sent_at"] is not None

    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["successful_count"] == 1
    assert row["processed_count"] == 1
    assert row["queued_count"] == 2


async def test_a_transient_failure_is_retried_behind_a_backoff(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    decision = await job_queue.fail_job(
        database, job, campaign, RESULT_NAVIGATION_TIMEOUT, "timed out", settings
    )
    assert decision["outcome"] == "retry"

    requeued = dict(await db.get_outreach_job(database, job["id"]))
    assert requeued["status"] == JOB_QUEUED
    assert requeued["worker_id"] is None
    assert requeued["run_after"] is not None
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_QUEUED
    assert target["error_message"] == "timed out"


async def test_retries_stop_at_the_limit_and_the_target_fails(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory(retry_limit=2)
    account = await account_factory()
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    outcomes = []
    for _ in range(3):
        job = await job_queue.claim_job(
            database, campaign["id"], account["id"], "w", settings
        )
        assert job is not None
        decision = await job_queue.fail_job(
            database, job, campaign, RESULT_NAVIGATION_TIMEOUT, "timed out", settings
        )
        outcomes.append(decision["outcome"])
        await _clear_backoff(database, job["id"])

    # retry_limit=2 → attempts 1 and 2 retry, attempt 3 is terminal.
    assert outcomes == ["retry", "retry", "fail"]
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_FAILED
    assert target["attempts"] == 3
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["failed_count"] == 1


async def test_a_terminal_result_skips_the_target_without_retrying(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    decision = await job_queue.fail_job(
        database, job, campaign, RESULT_MESSAGING_UNAVAILABLE, "DMs closed", settings
    )
    assert decision["outcome"] == "skip"
    assert dict(await db.get_outreach_job(database, job["id"]))["status"] == JOB_FAILED
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_SKIPPED


async def test_force_fail_skips_the_retry_budget(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    decision = await job_queue.fail_job(
        database, job, campaign, "template_error", "no value for {{offer}}",
        settings, force_fail=True,
    )
    assert decision["outcome"] == "fail"
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_FAILED


async def test_campaign_completes_when_every_target_is_resolved(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    for _ in range(3):
        job = await job_queue.claim_job(
            database, campaign["id"], account["id"], "w", settings
        )
        await job_queue.complete_job(database, job)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_COMPLETED
    assert row["successful_count"] == 3
    assert row["queued_count"] == 0


# --- crash recovery --------------------------------------------------------

async def test_reaper_requeues_a_job_whose_worker_died(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "doomed-worker", settings
    )
    await _expire_lease(database, job["id"])

    assert await job_queue.reap_stale_jobs(database, settings) == 1

    revived = dict(await db.get_outreach_job(database, job["id"]))
    assert revived["status"] == JOB_QUEUED
    assert revived["worker_id"] is None
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_QUEUED

    # And it can be picked up again — no work was lost. It queues behind
    # the jobs that have been waiting longer, so drain to find it.
    claimed = []
    while True:
        nxt = await job_queue.claim_job(
            database, campaign["id"], account["id"], "worker-b", settings
        )
        if nxt is None:
            break
        claimed.append(nxt)
    assert job["id"] in [c["id"] for c in claimed]
    retried = next(c for c in claimed if c["id"] == job["id"])
    assert retried["attempts"] == 2


async def test_reaper_fails_a_job_that_crashed_on_its_last_attempt(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory(retry_limit=0)
    account = await account_factory()
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "doomed", settings
    )
    await _expire_lease(database, job["id"])
    assert await job_queue.reap_stale_jobs(database, settings) == 1

    assert dict(await db.get_outreach_job(database, job["id"]))["status"] == JOB_FAILED
    target = dict(await db.get_outreach_target(database, job["target_id"]))
    assert target["status"] == TARGET_FAILED


async def test_reaper_leaves_a_live_lease_alone(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "alive", settings
    )
    assert await job_queue.reap_stale_jobs(database, settings) == 0
    assert dict(await db.get_outreach_job(database, job["id"]))["status"] == JOB_PROCESSING


# --- campaign controls -----------------------------------------------------

async def test_pause_then_resume_restores_the_queue(seeded, database):
    campaign, settings = seeded["campaign"], seeded["settings"]

    await job_queue.pause_campaign(database, campaign["id"])
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_PAUSED
    counts = await db.count_outreach_targets(database, campaign["id"])
    assert counts == {TARGET_PAUSED: 3}

    await job_queue.resume_campaign(database, row, settings)
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_RUNNING
    assert await db.count_outreach_targets(database, campaign["id"]) == {TARGET_QUEUED: 3}
    # The original jobs were reused, not duplicated.
    assert await job_queue.job_counts(database, campaign["id"]) == {JOB_QUEUED: 3}


async def test_pause_does_not_disturb_a_job_already_in_flight(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    await job_queue.pause_campaign(database, campaign["id"])
    assert dict(await db.get_outreach_job(database, job["id"]))["status"] == JOB_PROCESSING
    # The worker still records its result.
    await job_queue.complete_job(database, job)
    assert dict(await db.get_outreach_target(database, job["target_id"]))["status"] == TARGET_SENT


async def test_stop_cancels_queued_jobs_and_keeps_results(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    job = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    await job_queue.complete_job(database, job)

    await job_queue.stop_campaign(database, campaign["id"])
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["status"] == CAMPAIGN_STOPPED
    assert row["successful_count"] == 1
    counts = await job_queue.job_counts(database, campaign["id"])
    assert counts[JOB_CANCELLED] == 2
    assert counts[JOB_SUCCEEDED] == 1


async def test_retry_failed_requeues_only_failed_targets(seeded, database):
    campaign, account, settings = (
        seeded["campaign"], seeded["account"], seeded["settings"]
    )
    failed = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    await job_queue.fail_job(
        database, failed, campaign, RESULT_NAVIGATION_TIMEOUT, "boom",
        settings, force_fail=True,
    )
    skipped = await job_queue.claim_job(
        database, campaign["id"], account["id"], "w", settings
    )
    await job_queue.fail_job(
        database, skipped, campaign, RESULT_MESSAGING_UNAVAILABLE, "closed", settings
    )

    assert await job_queue.retry_failed(database, campaign["id"]) == 1
    counts = await db.count_outreach_targets(database, campaign["id"])
    assert counts[TARGET_QUEUED] == 2   # the retried one plus the untouched one
    assert counts[TARGET_SKIPPED] == 1

    created = await job_queue.enqueue_campaign(database, campaign, settings)
    assert created == 1


async def test_counters_are_recomputed_not_incremented(seeded, database):
    """A manually corrupted counter heals on the next refresh."""
    campaign = seeded["campaign"]
    await db.update_outreach_campaign(
        database, campaign["id"], successful_count=999, failed_count=999
    )
    totals = await stats.refresh_campaign_totals(database, campaign["id"])
    assert totals["successful_count"] == 0
    assert totals["failed_count"] == 0
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["successful_count"] == 0
