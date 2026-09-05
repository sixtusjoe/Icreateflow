"""The outreach job queue.

Postgres *is* the queue. There is no Redis, no Celery, no broker — the
same choice the Clipping dispatcher already makes in this codebase
(`services/clip_scheduler.py` claims due slots with `FOR UPDATE …
SKIP LOCKED`), and it buys the property that matters most here: campaign
state and queue state commit together, so a worker that dies mid-send
cannot leave them disagreeing.

Guarantees
----------
* **No double send.** A partial unique index (`outreach_jobs_one_live_per_target`)
  permits one queued-or-processing job per target, and claims are taken
  with `FOR UPDATE SKIP LOCKED`, so two workers never get the same row.
* **Crash recovery.** A claim writes `worker_id` and `lease_expires_at`.
  `reap_stale_jobs` returns any job whose lease has expired to the queue.
  A killed worker costs one lease interval, never a lost target.
* **Bounded retries.** Every claim increments `attempts`; past the retry
  limit a failure is terminal instead of looping forever.
* **Restartable.** All state lives in rows. Stop every worker, start them
  again tomorrow, and the campaign continues where it stopped.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

import database as db
from services.outreach import config as cfg
from services.outreach import stats
from services.outreach.constants import (
    CAMPAIGN_PAUSED,
    CAMPAIGN_RUNNING,
    CAMPAIGN_STOPPED,
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_PROCESSING,
    JOB_QUEUED,
    JOB_SUCCEEDED,
    TARGET_FAILED,
    TARGET_PAUSED,
    TARGET_PROCESSING,
    TARGET_QUEUED,
    TARGET_SENT,
    TARGET_SKIPPED,
    NEVER_RETRY_RESULTS,
    TERMINAL_RESULTS,
)

#: UTC "now" as a naive timestamp, in SQL. The TIMESTAMP columns hold UTC;
#: a bare NOW() would write the database server's local time.
UTC_NOW = "(NOW() AT TIME ZONE 'UTC')"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def retry_limit_for(campaign: dict, settings: dict[str, Any]) -> int:
    return cfg.campaign_limit(campaign, settings, "retry_limit", "outreach_retry_limit")


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

async def enqueue_campaign(database, campaign: dict, settings: dict[str, Any]) -> int:
    """Create one queued job per queued target. Returns how many were added.

    Idempotent by construction: the `NOT EXISTS` guard plus the partial
    unique index mean pressing Start twice, or a start racing a worker,
    adds nothing the second time.
    """
    campaign_id = campaign["id"]
    max_jobs = cfg.campaign_limit(
        campaign, settings, "max_jobs", "outreach_max_jobs_per_campaign"
    )
    session = database.session

    live = (await session.execute(
        text(
            "SELECT COUNT(*) FROM outreach_jobs "
            " WHERE campaign_id = :cid AND status <> :cancelled"
        ),
        {"cid": campaign_id, "cancelled": JOB_CANCELLED},
    )).scalar_one()
    room = max_jobs - int(live or 0)
    if room <= 0:
        return 0

    rows = (await session.execute(
        text(
            f"""
            INSERT INTO outreach_jobs
                    (campaign_id, target_id, status, attempts, run_after,
                     created_at, updated_at)
            SELECT t.campaign_id, t.id, :queued, 0, {UTC_NOW}, {UTC_NOW}, {UTC_NOW}
              FROM outreach_targets t
             WHERE t.campaign_id = :cid
               AND t.status = :target_queued
               AND NOT EXISTS (
                     SELECT 1 FROM outreach_jobs j
                      WHERE j.target_id = t.id
                        AND j.status IN (:queued, :processing)
                   )
             ORDER BY t.id ASC
             LIMIT :room
            ON CONFLICT DO NOTHING
            RETURNING id
            """
        ),
        {
            "cid": campaign_id,
            "queued": JOB_QUEUED,
            "processing": JOB_PROCESSING,
            "target_queued": TARGET_QUEUED,
            "room": room,
        },
    )).all()
    await session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

async def runnable_campaign_ids(database, limit: int = 20) -> list[int]:
    """Campaigns with work a worker could pick up right now."""
    session = database.session
    rows = (await session.execute(
        text(
            f"""
            SELECT DISTINCT c.id
              FROM outreach_campaigns c
              JOIN outreach_jobs j ON j.campaign_id = c.id
             WHERE c.status = :running
               AND j.status = :queued
               AND (j.run_after IS NULL OR j.run_after <= {UTC_NOW})
             ORDER BY c.id ASC
             LIMIT :limit
            """
        ),
        {"running": CAMPAIGN_RUNNING, "queued": JOB_QUEUED, "limit": limit},
    )).all()
    return [int(r[0]) for r in rows]


async def claim_job(
    database,
    campaign_id: int,
    account_id: Optional[int],
    worker_id: str,
    settings: dict[str, Any],
) -> Optional[dict]:
    """Claim the next job of a campaign for `account_id`.

    One statement: pick the oldest claimable job with `FOR UPDATE …
    SKIP LOCKED`, stamp the worker and lease on it, and hand it back. The
    target is flipped to `processing` in the same transaction, so a target
    is never visibly idle while a job for it is in flight.
    """
    lease_seconds = int(settings["outreach_job_lease_seconds"])
    session = database.session
    row = (await session.execute(
        text(
            f"""
            UPDATE outreach_jobs
               SET status = :processing,
                   sending_account_id = COALESCE(:account_id, sending_account_id),
                   worker_id = :worker_id,
                   attempts = attempts + 1,
                   started_at = {UTC_NOW},
                   lease_expires_at = {UTC_NOW} + (:lease * INTERVAL '1 second'),
                   error_message = NULL,
                   updated_at = {UTC_NOW}
             WHERE id = (
                   SELECT j.id
                     FROM outreach_jobs j
                     JOIN outreach_campaigns c ON c.id = j.campaign_id
                    WHERE j.campaign_id = :cid
                      AND j.status = :queued
                      AND c.status = :running
                      AND (j.run_after IS NULL OR j.run_after <= {UTC_NOW})
                    ORDER BY j.run_after ASC NULLS FIRST, j.id ASC
                    LIMIT 1
                    FOR UPDATE OF j SKIP LOCKED
             )
            RETURNING *
            """
        ),
        {
            "cid": campaign_id,
            "account_id": account_id,
            "worker_id": worker_id,
            "lease": lease_seconds,
            "queued": JOB_QUEUED,
            "processing": JOB_PROCESSING,
            "running": CAMPAIGN_RUNNING,
        },
    )).mappings().first()
    if not row:
        await session.commit()
        return None

    job = dict(row)
    await session.execute(
        text(
            f"UPDATE outreach_targets "
            f"   SET status = :processing, assigned_account_id = :account_id, "
            f"       attempts = attempts + 1, last_attempt_at = {UTC_NOW}, "
            f"       updated_at = {UTC_NOW} "
            f" WHERE id = :tid"
        ),
        {
            "tid": job["target_id"],
            "processing": TARGET_PROCESSING,
            "account_id": account_id,
        },
    )
    await session.commit()
    return job


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

async def complete_job(database, job: dict, result_status: str = "sent") -> None:
    """Record a delivered message: job succeeded, target sent."""
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_jobs "
            f"   SET status = :succeeded, result_status = :result, error_message = NULL, "
            f"       completed_at = {UTC_NOW}, worker_id = NULL, lease_expires_at = NULL, "
            f"       updated_at = {UTC_NOW} "
            f" WHERE id = :id"
        ),
        {"id": job["id"], "succeeded": JOB_SUCCEEDED, "result": result_status},
    )
    await session.execute(
        text(
            f"UPDATE outreach_targets "
            f"   SET status = :sent, sent_at = {UTC_NOW}, error_message = NULL, "
            f"       updated_at = {UTC_NOW} "
            f" WHERE id = :tid"
        ),
        {"tid": job["target_id"], "sent": TARGET_SENT},
    )
    await session.commit()
    await stats.refresh_and_maybe_complete(database, job["campaign_id"])


async def fail_job(
    database,
    job: dict,
    campaign: dict,
    result_status: str,
    error: Optional[str],
    settings: dict[str, Any],
    force_fail: bool = False,
) -> dict[str, Any]:
    """Record a failed attempt and decide what happens next.

    Three outcomes:

    * **skip** — the result is terminal for this target (no such profile,
      DMs closed). Retrying cannot change it.
    * **retry** — transient, and the retry budget is not spent. The job
      goes back to `queued` behind a backoff and the target returns to
      `queued` with the error kept for the dashboard.
    * **fail** — the budget is spent, or `force_fail` says this failure is
      not worth retrying (a template that cannot render for this target
      will not render on the second try either). Job and target both end
      failed.
    """
    limit = retry_limit_for(campaign, settings)
    backoff = int(settings["outreach_retry_backoff_seconds"])
    attempts = int(job.get("attempts") or 1)
    message = (error or result_status or "Unknown error")[:2000]
    session = database.session

    terminal = result_status in TERMINAL_RESULTS
    can_retry = (
        (not terminal)
        and (not force_fail)
        and result_status not in NEVER_RETRY_RESULTS
        and attempts <= limit
    )
    outcome = "retry" if can_retry else ("skip" if terminal else "fail")

    if can_retry:
        await session.execute(
            text(
                f"UPDATE outreach_jobs "
                f"   SET status = :queued, result_status = :result, error_message = :err, "
                f"       worker_id = NULL, lease_expires_at = NULL, "
                f"       run_after = {UTC_NOW} + (:delay * INTERVAL '1 second'), "
                f"       updated_at = {UTC_NOW} "
                f" WHERE id = :id"
            ),
            {
                "id": job["id"], "queued": JOB_QUEUED, "result": result_status,
                "err": message, "delay": backoff * attempts,
            },
        )
        target_status = TARGET_QUEUED
    else:
        await session.execute(
            text(
                f"UPDATE outreach_jobs "
                f"   SET status = :failed, result_status = :result, error_message = :err, "
                f"       completed_at = {UTC_NOW}, worker_id = NULL, lease_expires_at = NULL, "
                f"       updated_at = {UTC_NOW} "
                f" WHERE id = :id"
            ),
            {"id": job["id"], "failed": JOB_FAILED, "result": result_status, "err": message},
        )
        target_status = TARGET_SKIPPED if terminal else TARGET_FAILED

    await session.execute(
        text(
            f"UPDATE outreach_targets "
            f"   SET status = :status, error_message = :err, updated_at = {UTC_NOW} "
            f" WHERE id = :tid"
        ),
        {"tid": job["target_id"], "status": target_status, "err": message},
    )
    await session.commit()
    await stats.refresh_and_maybe_complete(database, job["campaign_id"])
    return {"outcome": outcome, "attempts": attempts, "retry_limit": limit}


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------

async def reap_stale_jobs(database, settings: dict[str, Any]) -> int:
    """Requeue jobs whose worker died holding them.

    A job is stale when it is `processing` and its lease has expired. It
    goes straight back to `queued` (claimable immediately — the previous
    attempt produced no result, so there is nothing to back off from), and
    its target with it. Jobs that have exhausted their retry budget are
    failed instead of looping.

    This is the whole of the crash-recovery story: nothing is held in
    worker memory, so nothing else needs restoring.
    """
    limit = int(settings["outreach_retry_limit"])
    session = database.session

    revived = (await session.execute(
        text(
            f"""
            UPDATE outreach_jobs j
               SET status = :queued,
                   worker_id = NULL,
                   lease_expires_at = NULL,
                   run_after = {UTC_NOW},
                   error_message = COALESCE(j.error_message,
                                            'Worker lease expired — requeued'),
                   updated_at = {UTC_NOW}
             WHERE j.status = :processing
               AND j.lease_expires_at IS NOT NULL
               AND j.lease_expires_at < {UTC_NOW}
               AND j.attempts <= COALESCE(
                     (SELECT c.retry_limit FROM outreach_campaigns c WHERE c.id = j.campaign_id),
                     :limit)
            RETURNING j.id, j.target_id
            """
        ),
        {"queued": JOB_QUEUED, "processing": JOB_PROCESSING, "limit": limit},
    )).all()

    exhausted = (await session.execute(
        text(
            f"""
            UPDATE outreach_jobs j
               SET status = :failed,
                   result_status = COALESCE(j.result_status, 'worker_crash'),
                   error_message = 'Worker lease expired after the final attempt',
                   completed_at = {UTC_NOW},
                   worker_id = NULL,
                   lease_expires_at = NULL,
                   updated_at = {UTC_NOW}
             WHERE j.status = :processing
               AND j.lease_expires_at IS NOT NULL
               AND j.lease_expires_at < {UTC_NOW}
            RETURNING j.id, j.target_id, j.campaign_id
            """
        ),
        {"failed": JOB_FAILED, "processing": JOB_PROCESSING},
    )).all()

    if revived:
        await session.execute(
            text(
                f"UPDATE outreach_targets "
                f"   SET status = :queued, updated_at = {UTC_NOW} "
                f" WHERE id = ANY(:ids) AND status = :processing"
            ),
            {
                "ids": [int(r[1]) for r in revived],
                "queued": TARGET_QUEUED,
                "processing": TARGET_PROCESSING,
            },
        )
    if exhausted:
        await session.execute(
            text(
                f"UPDATE outreach_targets "
                f"   SET status = :failed, "
                f"       error_message = 'Worker crashed on the final attempt', "
                f"       updated_at = {UTC_NOW} "
                f" WHERE id = ANY(:ids) AND status = :processing"
            ),
            {
                "ids": [int(r[1]) for r in exhausted],
                "failed": TARGET_FAILED,
                "processing": TARGET_PROCESSING,
            },
        )
    await session.commit()

    for campaign_id in {int(r[2]) for r in exhausted}:
        await stats.refresh_and_maybe_complete(database, campaign_id)
    return len(revived) + len(exhausted)


# ---------------------------------------------------------------------------
# Campaign controls
# ---------------------------------------------------------------------------

async def start_campaign(database, campaign: dict, settings: dict[str, Any]) -> int:
    """Move a campaign to running and enqueue its targets.

    Paused targets are returned to `queued` first, so start doubles as
    "resume from stopped".
    """
    campaign_id = campaign["id"]
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_targets SET status = :queued, updated_at = {UTC_NOW} "
            f" WHERE campaign_id = :cid AND status = :paused"
        ),
        {"cid": campaign_id, "queued": TARGET_QUEUED, "paused": TARGET_PAUSED},
    )
    await session.commit()
    await db.update_outreach_campaign(database, campaign_id, status=CAMPAIGN_RUNNING)
    created = await enqueue_campaign(
        database, {**campaign, "status": CAMPAIGN_RUNNING}, settings
    )
    await stats.refresh_campaign_totals(database, campaign_id)
    return created


async def pause_campaign(database, campaign_id: int) -> None:
    """Stop dispatching without losing position.

    Queued targets are marked `paused` so the target list shows the truth;
    their jobs stay queued and become claimable again the moment the
    campaign is running. Jobs already in flight are left alone — the
    worker finishes and records the result.
    """
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_targets SET status = :paused, updated_at = {UTC_NOW} "
            f" WHERE campaign_id = :cid AND status = :queued"
        ),
        {"cid": campaign_id, "paused": TARGET_PAUSED, "queued": TARGET_QUEUED},
    )
    await session.commit()
    await db.update_outreach_campaign(database, campaign_id, status=CAMPAIGN_PAUSED)
    await stats.refresh_campaign_totals(database, campaign_id)


async def resume_campaign(database, campaign: dict, settings: dict[str, Any]) -> int:
    """Undo a pause and top the queue back up."""
    return await start_campaign(database, campaign, settings)


async def stop_campaign(database, campaign_id: int) -> None:
    """End the run: cancel everything queued, keep every result.

    Targets go to `paused` rather than a terminal status so the campaign
    can be started again later without re-importing.
    """
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_jobs SET status = :cancelled, completed_at = {UTC_NOW}, "
            f"       worker_id = NULL, lease_expires_at = NULL, updated_at = {UTC_NOW} "
            f" WHERE campaign_id = :cid AND status = :queued"
        ),
        {"cid": campaign_id, "cancelled": JOB_CANCELLED, "queued": JOB_QUEUED},
    )
    await session.execute(
        text(
            f"UPDATE outreach_targets SET status = :paused, updated_at = {UTC_NOW} "
            f" WHERE campaign_id = :cid AND status = :queued"
        ),
        {"cid": campaign_id, "paused": TARGET_PAUSED, "queued": TARGET_QUEUED},
    )
    await session.commit()
    await db.update_outreach_campaign(database, campaign_id, status=CAMPAIGN_STOPPED)
    await stats.refresh_campaign_totals(database, campaign_id)


async def hold_job(database, job: dict, result_status: str, error: str | None,
                   delay_seconds: int) -> None:
    """Put a job back on the queue after a deliberate wait.

    Not a failure and not an attempt: the driver did what it was asked and
    chose to come back later. Counting it against the retry budget would
    mean a campaign that follows first runs out of attempts before it ever
    sends anything.
    """
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_jobs "
            f"   SET status = :queued, result_status = :result, "
            f"       error_message = :err, worker_id = NULL, "
            f"       lease_expires_at = NULL, "
            f"       attempts = GREATEST(attempts - 1, 0), "
            f"       run_after = {UTC_NOW} + (:delay * INTERVAL \'1 second\'), "
            f"       updated_at = {UTC_NOW} "
            f" WHERE id = :id"
        ),
        {
            "id": job["id"], "queued": JOB_QUEUED, "result": result_status,
            "err": (error or result_status)[:2000], "delay": max(int(delay_seconds), 0),
        },
    )
    await session.commit()


async def retry_failed(database, campaign_id: int) -> int:
    """Put failed targets back in the queue. Returns how many were reset.

    Only `failed` targets — `skipped` ones (no such profile, DMs closed)
    would fail again identically.
    """
    session = database.session
    rows = (await session.execute(
        text(
            f"UPDATE outreach_targets "
            f"   SET status = :queued, error_message = NULL, updated_at = {UTC_NOW} "
            f" WHERE campaign_id = :cid AND status = :failed "
            f"RETURNING id"
        ),
        {"cid": campaign_id, "queued": TARGET_QUEUED, "failed": TARGET_FAILED},
    )).all()
    await session.commit()
    await stats.refresh_campaign_totals(database, campaign_id)
    return len(rows)


async def job_counts(database, campaign_id: int) -> dict[str, int]:
    session = database.session
    rows = (await session.execute(
        text(
            "SELECT status, COUNT(*) FROM outreach_jobs "
            " WHERE campaign_id = :cid GROUP BY status"
        ),
        {"cid": campaign_id},
    )).all()
    return {str(r[0]): int(r[1]) for r in rows}
