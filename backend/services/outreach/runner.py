"""The browser worker — the loop that turns queued jobs into sent messages.

One cycle:

    pick a running campaign
      → lease a free sending account for it        (accounts.lease_account)
      → claim one of its jobs for that account     (queue.claim_job)
      → render the message                         (templates.render)
      → hand account + target + message to the driver
      → record the structured result               (queue.complete_job / fail_job)
      → release the account lease

Nothing about a web page appears in this file: the driver behind
`services.outreach.browser.get_driver` is the only thing that knows, and
swapping it is a config change (`outreach_driver` in site_config), not a
code change.

The worker holds no durable state. Kill it at any point and the claimed
job's lease expires; `queue.reap_stale_jobs` puts it back. That is why
this can run as N independent processes without coordination.
"""
from __future__ import annotations

import asyncio
import os
import socket
import traceback
import uuid
from typing import Any, Optional

import database as db
from services.outreach import accounts as account_mgr
from services.outreach import config as cfg
from services.outreach import queue as job_queue
from services.outreach import templates as template_svc
from services.outreach.browser import DriverUnavailable, MessageResult, get_driver
from services.outreach.constants import (
    RESULT_DB_ERROR,
    RESULT_FOLLOW_PENDING,
    RESULT_TEMPLATE_ERROR,
    RESULT_UNKNOWN,
)
from services.outreach.crypto import decrypt_session

def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class OutreachWorker:
    """Runs jobs until stopped.

    driver_name
        Overrides the `outreach_driver` site_config value. Tests pass a
        pre-built mock via `driver` instead.
    once
        Process at most one batch and return — used by tests and by
        `--once` on the CLI.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        driver_name: Optional[str] = None,
        driver: Any = None,
        concurrency: Optional[int] = None,
        once: bool = False,
    ):
        self.worker_id = worker_id or default_worker_id()
        self.driver_name = driver_name
        self._driver = driver
        self._driver_started = driver is not None
        self.concurrency_override = concurrency
        self.once = once
        self._stopping = asyncio.Event()

    # --- lifecycle -------------------------------------------------------

    async def _get_driver(self, settings: dict[str, Any]):
        if self._driver is None:
            name = self.driver_name or settings[cfg.DRIVER_KEY]
            self._driver = get_driver(name)
        if not self._driver_started:
            await self._driver.startup()
            self._driver_started = True
        return self._driver

    async def shutdown(self) -> None:
        self._stopping.set()
        if self._driver is not None and self._driver_started:
            try:
                await self._driver.shutdown()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                traceback.print_exc()
            self._driver_started = False

    def stop(self) -> None:
        self._stopping.set()

    # --- one job ---------------------------------------------------------

    async def process_one(self, settings: dict[str, Any]) -> bool:
        """Claim and run at most one job. True if work was done."""
        database = await db.get_db()
        account: Optional[dict] = None
        job: Optional[dict] = None
        try:
            for campaign_id in await job_queue.runnable_campaign_ids(database):
                campaign = await db.get_outreach_campaign(database, campaign_id)
                if not campaign:
                    continue
                campaign = dict(campaign)

                account = await account_mgr.lease_account(database, campaign, settings)
                if account is None:
                    # Every eligible account is busy, cooling down, capped
                    # or paused — try the next campaign rather than
                    # claiming a job nobody can run.
                    continue

                job = await job_queue.claim_job(
                    database, campaign_id, int(account["id"]), self.worker_id, settings
                )
                if job is None:
                    await account_mgr.release_account(database, int(account["id"]))
                    account = None
                    continue

                await self._run_job(database, campaign, account, job, settings)
                return True
            return False
        except Exception:  # noqa: BLE001 — a worker must survive anything
            traceback.print_exc()
            await self._record_worker_error(database, job, account)
            return False
        finally:
            if account is not None:
                try:
                    await account_mgr.release_account(database, int(account["id"]))
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
            await database.close()

    async def _record_worker_error(
        self, database, job: Optional[dict], account: Optional[dict]
    ) -> None:
        """Log an unexpected worker fault against the job it was running.

        The job itself is deliberately left `processing`: its lease will
        expire and the reaper decides retry-or-fail with the same rules
        every other failure goes through.
        """
        try:
            await db.log_error(
                database,
                "outreach.worker",
                f"Worker {self.worker_id} raised while processing "
                f"job={job.get('id') if job else None}",
                traceback=traceback.format_exc(),
                context=f"account_id={account.get('id') if account else None}",
            )
        except Exception:  # noqa: BLE001
            pass

    async def _run_job(
        self,
        database,
        campaign: dict,
        account: dict,
        job: dict,
        settings: dict[str, Any],
    ) -> None:
        target_row = await db.get_outreach_target(database, job["target_id"])
        if not target_row:
            await job_queue.fail_job(
                database, job, campaign, RESULT_DB_ERROR,
                "Target row disappeared", settings, force_fail=True,
            )
            return
        target = dict(target_row)

        # --- render (never send a half-substituted message) --------------
        try:
            message = template_svc.render(
                campaign.get("message_template") or "",
                template_svc.build_variables(target, campaign, account),
            )
        except template_svc.TemplateError as exc:
            await job_queue.fail_job(
                database, job, campaign, RESULT_TEMPLATE_ERROR, str(exc),
                settings, force_fail=True,
            )
            return

        # --- send --------------------------------------------------------
        driver = await self._get_driver(settings)
        payload = {
            "id": int(account["id"]),
            "name": account.get("name"),
            "platform": account.get("platform"),
            "session_state": decrypt_session(account.get("session_state_encrypted")),
            "session_reference": account.get("session_reference"),
        }
        try:
            result = await driver.send_message(
                payload,
                {
                    "username": target["username"],
                    "profile_url": target["profile_url"],
                    "follow_wait_seconds": int(
                        settings.get("outreach_follow_wait_seconds") or 0
                    ),
                },
                message,
            )
            if not isinstance(result, MessageResult):
                result = MessageResult.failure(
                    RESULT_UNKNOWN, f"Driver returned {type(result).__name__}, not MessageResult"
                )
        except Exception as exc:  # noqa: BLE001 — a driver bug is a job failure
            traceback.print_exc()
            result = MessageResult.failure(
                RESULT_UNKNOWN, f"{type(exc).__name__}: {exc}"[:500]
            )
        finally:
            # Drop the per-account browser context but keep its session.
            try:
                await driver.release_account(int(account["id"]))
            except Exception:  # noqa: BLE001
                traceback.print_exc()

        await self._record_result(database, campaign, account, job, target, result, settings)

    async def _record_result(
        self,
        database,
        campaign: dict,
        account: dict,
        job: dict,
        target: dict,
        result: MessageResult,
        settings: dict[str, Any],
    ) -> None:
        """Persist one attempt — the result processor."""
        account_id = int(account["id"])
        if result.status == RESULT_FOLLOW_PENDING:
            # Neither a send nor a failure — the target was followed and the
            # message deliberately deferred. Nobody is blamed for it.
            await job_queue.hold_job(
                database, job, result.status, result.error,
                int(settings.get("outreach_follow_wait_seconds") or 0),
            )
            return
        if result.success:
            await job_queue.complete_job(database, job, result.status)
            await account_mgr.record_success(database, account_id)
            return

        decision = await job_queue.fail_job(
            database, job, campaign, result.status, result.error, settings
        )
        health = await account_mgr.record_failure(
            database, account_id, result.status, result.error, settings,
            user_id=campaign.get("user_id"),
        )
        await db.log_error(
            database,
            "outreach.send",
            f"{result.status}: {result.error or ''}"[:2000],
            user_id=campaign.get("user_id"),
            context=(
                f"campaign_id={campaign['id']} job_id={job['id']} "
                f"target={target.get('username')} account_id={account_id} "
                f"outcome={decision['outcome']}"
            ),
            level="warning",
        )
        if health.get("paused"):
            # The account is now `paused`, and `release_account` only
            # touches rows still `active` — so the lease release at the end
            # of process_one() cannot silently un-pause it.
            await db.log_outreach_audit(
                database, "account.paused_during_job", "campaign", campaign["id"],
                user_id=campaign.get("user_id"),
                detail=f"account_id={account_id}: {health.get('reason')}",
            )

    # --- loop ------------------------------------------------------------

    async def _slot(self) -> None:
        """One concurrent processing slot."""
        while not self._stopping.is_set():
            database = await db.get_db()
            try:
                settings = await cfg.get_all(database)
            finally:
                await database.close()

            if not settings[cfg.WORKERS_ENABLED_KEY]:
                # Admin pressed "Stop all workers" — stay alive, do nothing.
                await self._sleep(settings["outreach_worker_idle_seconds"])
                if self.once:
                    return
                continue

            try:
                did_work = await self.process_one(settings)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                did_work = False

            if self.once:
                return
            if not did_work:
                await self._sleep(settings["outreach_worker_idle_seconds"])

    async def _sleep(self, seconds: float) -> None:
        """Interruptible sleep — a stop signal doesn't wait out the idle."""
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _maintenance(self) -> None:
        """Reaper: requeue crashed jobs, free stranded account leases."""
        while not self._stopping.is_set():
            database = await db.get_db()
            try:
                settings = await cfg.get_all(database)
                await job_queue.reap_stale_jobs(database, settings)
                await account_mgr.release_expired_leases(database, settings)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                await database.close()
            if self.once:
                return
            await self._sleep(60)

    async def run(self) -> None:
        """Start the slots and the reaper; return when stopped."""
        database = await db.get_db()
        try:
            settings = await cfg.get_all(database)
        finally:
            await database.close()

        concurrency = int(
            self.concurrency_override or settings["outreach_worker_concurrency"]
        )
        try:
            await self._get_driver(settings)
        except DriverUnavailable:
            await self.shutdown()
            raise

        tasks = [asyncio.create_task(self._maintenance())]
        tasks += [asyncio.create_task(self._slot()) for _ in range(concurrency)]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await self.shutdown()


async def run_once(driver: Any = None, worker_id: str = "test-worker") -> bool:
    """Process a single job with a caller-supplied driver.

    The seam the tests drive: no loop, no sleeping, no browser.
    """
    worker = OutreachWorker(worker_id=worker_id, driver=driver, once=True)
    database = await db.get_db()
    try:
        settings = await cfg.get_all(database)
    finally:
        await database.close()
    return await worker.process_one(settings)


# ---------------------------------------------------------------------------
# In-process maintenance (started from FastAPI's lifespan)
# ---------------------------------------------------------------------------

async def _maintenance_loop() -> None:
    """Reaper only — never sends anything.

    The API process must not drive a browser: it runs with `-w 1` under
    gunicorn and a hung Playwright call would block the event loop serving
    every request. Sending lives in the standalone worker
    (`python scripts/outreach_worker.py`). What runs here is the cheap,
    DB-only recovery pass, so a crashed worker's jobs are requeued even if
    no worker is currently up.
    """
    await asyncio.sleep(20)  # let startup logs flush, like clip_scheduler
    while True:
        database = None
        try:
            database = await db.get_db()
            settings = await cfg.get_all(database)
            await job_queue.reap_stale_jobs(database, settings)
            await account_mgr.release_expired_leases(database, settings)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            if database is not None:
                await database.close()
        await asyncio.sleep(120)


async def start_background_tasks() -> list[asyncio.Task]:
    """Kick off the outreach maintenance loop. Call from FastAPI lifespan."""
    return [asyncio.create_task(_maintenance_loop())]
