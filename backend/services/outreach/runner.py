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
import time
import traceback
import uuid
from typing import Any, Optional

import database as db
from services.outreach import accounts as account_mgr
from services.outreach import config as cfg, session_capture
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

#: Which driver serves which platform. Adding a platform is this line plus
#: a selector table — the engine underneath is shared.
PLATFORM_DRIVERS: dict[str, str] = {
    "tiktok": "playwright_tiktok",
    "instagram": "playwright_instagram",
}


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


#: How often one campaign may report why it cannot send. It reports the
#: same thing every cycle until someone acts on it, and a worker that logs
#: every ten seconds is a worker nobody reads.
EXPLAIN_IDLE_SECONDS = int(os.environ.get("ICREATE_OUTREACH_EXPLAIN_IDLE_SECONDS", "600"))

#: How long a shutdown waits for sends already in flight to finish.
#:
#: Restarting the API used to kill the worker mid-job: the browser died
#: between clicking Send and confirming it, the job stayed `processing`
#: holding a ten-minute lease, and the account stayed `active` and
#: unleasable for the same ten minutes. Nothing was lost — the reaper
#: requeues it — but the campaign stopped dead and said nothing, and the
#: requeued target had to be sent again without knowing whether the first
#: attempt had landed.
#:
#: Long enough for a send to finish (~40s, and a slow profile longer),
#: short enough that a deploy is not held hostage by a stuck page.
DRAIN_SECONDS = int(os.environ.get("ICREATE_OUTREACH_DRAIN_SECONDS", "90"))


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
        headless: Optional[bool] = None,
    ):
        self.worker_id = worker_id or default_worker_id()
        self.driver_name = driver_name
        self._driver = driver
        self._driver_started = driver is not None
        #: One live driver per platform in play, started on first use.
        self._drivers: dict[str, Any] = {}
        self._driver_lock = asyncio.Lock()
        self.concurrency_override = concurrency
        self.once = once
        #: None leaves it to the driver's own default. False is how a local
        #: worker keeps every window on screen — the operator has to be able
        #: to reach a verification puzzle, whichever platform threw it.
        self._headless = headless
        self._stopping = asyncio.Event()
        #: campaign id -> when its idleness was last explained. Keeps a
        #: permanently stuck campaign from writing the same line every cycle.
        self._explained: dict[int, float] = {}

    # --- lifecycle -------------------------------------------------------

    def _pinned_driver(self, settings: dict[str, Any]) -> Optional[str]:
        """A driver chosen deliberately for every job, or None to route.

        Only two things pin: `--driver` on the command line, and `mock` in
        the settings. Both are explicit statements about what should happen
        to every job regardless of platform, and mock in particular is a
        deliberate "contact nothing" that must never be quietly overridden.

        A settings value naming one real driver does NOT pin. Installs
        configured before there was more than one platform still say
        `playwright_tiktok`, and honouring that literally would hand
        Instagram jobs to TikTok's selector table — which would find
        nothing, on every send, for a reason nobody would guess from the
        outside.
        """
        if self.driver_name:
            return self.driver_name
        configured = (settings.get(cfg.DRIVER_KEY) or "").strip()
        return configured if configured == "mock" else None

    def _driver_name_for(self, settings: dict[str, Any], platform: Optional[str]) -> str:
        """Which driver sends for this account.

        The account's platform decides, unless something pinned it. One
        worker serves campaigns on every platform, and a TikTok selector
        table has nothing useful to say about an Instagram profile.
        """
        pinned = self._pinned_driver(settings)
        if pinned:
            return pinned
        name = PLATFORM_DRIVERS.get((platform or "").strip().lower())
        if not name:
            raise DriverUnavailable(
                f"No driver for platform {platform!r}. "
                f"Known platforms: {', '.join(sorted(PLATFORM_DRIVERS))}."
            )
        return name

    async def _get_driver(self, settings: dict[str, Any], platform: Optional[str] = None):
        # A driver handed in directly (tests, rehearsals) is used as-is.
        if self._driver is not None:
            if not self._driver_started:
                await self._driver.startup()
                self._driver_started = True
            return self._driver

        name = self._driver_name_for(settings, platform)
        driver = self._drivers.get(name)
        if driver is not None:
            return driver
        # Two slots starting together both find nothing here and both build
        # a driver, which means two browsers launched and one of them
        # orphaned — running, invisible to shutdown, holding a profile open.
        async with self._driver_lock:
            driver = self._drivers.get(name)
            if driver is None:
                kwargs = {} if self._headless is None else {"headless": self._headless}
                driver = get_driver(name, **kwargs)
                await driver.startup()
                self._drivers[name] = driver
        return driver

    async def shutdown(self) -> None:
        self._stopping.set()
        if self._driver is not None and self._driver_started:
            try:
                await self._driver.shutdown()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                traceback.print_exc()
            self._driver_started = False
        for name, driver in list(self._drivers.items()):
            try:
                await driver.shutdown()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                traceback.print_exc()
            self._drivers.pop(name, None)

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
                    await self._explain_idleness(database, campaign, settings)
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
        driver = await self._get_driver(settings, account.get("platform"))
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
                    "follow_to_unlock": bool(
                        int(settings.get("outreach_follow_to_unlock") or 0)
                    ),
                    # The campaign's image, as a path the driver can hand to
                    # a file input. None when the campaign has no image.
                    "attachment_path": campaign.get("attachment_path"),
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

    async def _explain_idleness(
        self, database, campaign: dict, settings: dict[str, Any]
    ) -> None:
        """Say why a running campaign is not running, at most occasionally.

        A campaign that cannot lease an account keeps not leasing one, so
        this fires on every cycle — every ten seconds, forever. Logging it
        each time would bury the run; logging it never is what made two
        capped campaigns look like a crash. Once per campaign per interval
        is the compromise, and the state it reports does not change quickly.
        """
        campaign_id = int(campaign["id"])
        now = time.monotonic()
        last = self._explained.get(campaign_id, 0.0)
        if now - last < EXPLAIN_IDLE_SECONDS:
            return
        try:
            why = await account_mgr.explain_no_account(database, campaign, settings)
        except Exception:  # noqa: BLE001 — a diagnostic must not stop the worker
            return
        if not why:
            return
        self._explained[campaign_id] = now
        print(
            f"[outreach] campaign {campaign_id} "
            f"({campaign.get('name') or 'unnamed'}) has nothing it can send "
            f"with: {why}",
            flush=True,
        )

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
        # Fail fast on a driver that cannot load — but only when one is
        # pinned. Without a pin there is no single driver to check: each is
        # started the first time a job on its platform arrives.
        if self._pinned_driver(settings) or self._driver is not None:
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


def local_worker_enabled() -> bool:
    """Should this process send, as well as serve the API?

    False everywhere by default. On the server, sending belongs to the
    systemd workers: an API process that also drives browsers would restart
    with every deploy, mid-send. On a laptop there are no systemd workers,
    so without this "Start campaign" queues work that nothing ever claims —
    which looks exactly like the app being broken.
    """
    return (os.environ.get("ICREATE_OUTREACH_LOCAL_WORKER") or "").strip().lower() not in (
        "", "0", "false", "no", "off",
    )


def local_worker_running() -> bool:
    return _LOCAL_WORKER.get("running", False)


def local_worker_state() -> dict[str, Any]:
    return dict(_LOCAL_WORKER)


#: What the local sender is doing, for the campaign page to show.
#: `busy` counts the slots mid-job rather than answering yes/no, so the
#: dashboard can say "2 sending" instead of "sending". It stays truthy at
#: zero-or-more, which is all `sender_busy` ever asked of it.
_LOCAL_WORKER: dict[str, Any] = {
    "running": False, "busy": 0, "slots": 0, "last_error": None,
}


async def _local_slot(worker: "OutreachWorker", stopping: asyncio.Event) -> None:
    """One account's worth of work, running alongside the others.

    Slots do not divide up a queue between them — each one leases an
    account, and a lease is exclusive, so two slots always hold two
    different accounts and never race for the same target. An account
    carries its own send interval with it, so running two does not make
    either go faster; it makes two go at once, in two windows.
    """
    while not stopping.is_set():
        try:
            database = await db.get_db()
            try:
                settings = await cfg.get_all(database)
            finally:
                await database.close()

            if not settings[cfg.WORKERS_ENABLED_KEY]:
                await asyncio.sleep(int(settings["outreach_worker_idle_seconds"]))
                continue

            # Checked again here: the wait above is where a slot spends most
            # of its life, and claiming a job on the way out is the one
            # thing a draining worker must not do.
            if stopping.is_set():
                return

            _LOCAL_WORKER["busy"] += 1
            try:
                did_work = await worker.process_one(settings)
            finally:
                _LOCAL_WORKER["busy"] -= 1
            _LOCAL_WORKER["last_error"] = None
            if not did_work:
                # Nothing free — most often the other slot holds the only
                # account that can run. Idling is the whole answer.
                await asyncio.sleep(int(settings["outreach_worker_idle_seconds"]))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad job must not end
            # the sender; the next pass may be fine.
            _LOCAL_WORKER["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            traceback.print_exc()
            await asyncio.sleep(10)


async def _local_worker_loop() -> None:
    """Claim and send, in visible browsers, for as long as the API runs.

    Deliberately visible: this exists so a person can watch it and clear a
    puzzle when one appears. A headless local worker would hit the same
    challenge and simply pause the account, which is the situation this is
    meant to get out of.

    Several accounts at once, each in its own window. One shared browser
    with a context per account — contexts are what keep the sessions apart,
    and in a headed browser each one is its own window, so a puzzle on one
    account is reachable without stopping the others.
    """
    worker = OutreachWorker(headless=False)
    database = await db.get_db()
    try:
        settings = await cfg.get_all(database)
    finally:
        await database.close()
    slots = int(settings["outreach_local_worker_concurrency"])

    _LOCAL_WORKER["running"] = True
    _LOCAL_WORKER["slots"] = slots
    _LOCAL_WORKER["busy"] = 0
    print(
        f"[outreach] local sender started — {slots} "
        f"{'window' if slots == 1 else 'windows'}, visible",
        flush=True,
    )
    stopping = asyncio.Event()
    tasks = [asyncio.create_task(_local_slot(worker, stopping)) for _ in range(slots)]
    running = asyncio.gather(*tasks)
    try:
        # Shielded so that being cancelled does not tear the slots down with
        # it. Cancellation here means "the API is stopping", and a send that
        # is halfway through deserves to finish: the alternative is a job
        # abandoned between Send and the confirmation, which nobody can
        # later tell apart from one that never sent.
        await asyncio.shield(running)
    except asyncio.CancelledError:
        stopping.set()
        if _LOCAL_WORKER["busy"]:
            print(
                f"[outreach] shutting down — waiting up to {DRAIN_SECONDS}s for "
                f"{_LOCAL_WORKER['busy']} send(s) already in flight",
                flush=True,
            )
        try:
            async with asyncio.timeout(DRAIN_SECONDS):
                await running
        except (TimeoutError, asyncio.CancelledError):
            print(
                "[outreach] a send did not finish in time — its job keeps its "
                "lease and the reaper will requeue it",
                flush=True,
            )
        except Exception:  # noqa: BLE001 — a failing slot must not mask the stop
            traceback.print_exc()
        else:
            print("[outreach] all sends finished; stopping cleanly", flush=True)
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        _LOCAL_WORKER["running"] = False
        _LOCAL_WORKER["busy"] = 0
        _LOCAL_WORKER["slots"] = 0
        try:
            await worker.shutdown()
        except Exception:  # noqa: BLE001 — shutdown must not raise
            traceback.print_exc()


async def start_background_tasks() -> list[asyncio.Task]:
    """Kick off the outreach maintenance loop. Call from FastAPI lifespan."""
    tasks = [asyncio.create_task(_maintenance_loop())]
    if local_worker_enabled():
        tasks.append(asyncio.create_task(_local_worker_loop()))
    return tasks


async def stop_background_tasks(tasks: list[asyncio.Task]) -> None:
    """Ask the loops to stop, and wait while they finish what they started.

    Cancelling without awaiting is what made a restart destructive: the
    cancellation was delivered, the process exited, and a send in flight
    died between clicking Send and confirming it. The sender interprets
    cancellation as "drain", so the wait here is the half that gives it
    somewhere to drain into.

    Bounded, because a deploy cannot hang on a stuck page. Past the bound
    the tasks are gone and the job keeps its lease, which is exactly the
    situation the reaper already exists for.
    """
    # A sign-in window is a task in this process holding a headed browser,
    # so stopping now closes it under whoever is typing into it. It is not
    # ours to cancel and not ours to wait out forever either — but going
    # quietly is how someone loses a password entry three times in a row
    # and cannot see why.
    open_signins = session_capture.running_accounts()
    if open_signins:
        print(
            f"[outreach] {len(open_signins)} sign-in window(s) still open "
            f"(account(s) {', '.join(str(a) for a in open_signins)}) — waiting "
            f"up to {DRAIN_SECONDS}s; they close when this process exits",
            flush=True,
        )
        waited = 0.0
        while session_capture.any_running() and waited < DRAIN_SECONDS:
            await asyncio.sleep(1)
            waited += 1
        if session_capture.any_running():
            print(
                "[outreach] a sign-in is still open and is about to be closed "
                "by this shutdown — it will have to be started again",
                flush=True,
            )

    for task in tasks:
        task.cancel()
    if not tasks:
        return
    try:
        async with asyncio.timeout(DRAIN_SECONDS + 15):
            await asyncio.gather(*tasks, return_exceptions=True)
    except TimeoutError:
        print(
            "[outreach] background tasks did not stop in time — exiting anyway",
            flush=True,
        )
