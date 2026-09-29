"""The worker end to end, driven by the mock messenger.

Nothing here opens a browser or contacts a platform: every send goes
through `MockMessenger`, which records what it was asked to send and
returns whatever outcome the test scripts.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

import database as db
from services.outreach import accounts as account_mgr, importer, queue as job_queue, runner
from services.outreach.browser.mock import MockMessenger
from services.outreach.constants import (
    ACCOUNT_ACTIVE,
    ACCOUNT_IDLE,
    ACCOUNT_PAUSED,
    CAMPAIGN_COMPLETED,
    CAMPAIGN_PAUSED,
    CAMPAIGN_RUNNING,
    RESULT_FOLLOW_LIMITED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_SUCCEEDED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_SESSION_EXPIRED,
    TARGET_FAILED,
    TARGET_QUEUED,
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


async def test_a_closed_inbox_is_retried_and_does_not_blame_the_account(
    seeded, database
):
    """No Message button is an absence, and an absence is not a verdict.

    This asserted the opposite until the database-backed tests were first
    run: that the target was skipped for good. Three live targets were lost
    that way to causes that had nothing to do with them, so the result was
    made retryable. The half of the test that still holds is the half about
    the account — a target-side problem is not the sender's fault.
    """
    driver = MockMessenger(outcomes=[(RESULT_MESSAGING_UNAVAILABLE, "DMs closed")])
    await _run(driver, seeded["settings"])

    jobs = [dict(j) for j in await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"]
    )]
    # The campaign is seeded with three targets, so the other two are still
    # queued and untouched. The one that ran is the one with an attempt on it.
    attempted = [j for j in jobs if j["attempts"] > 0]
    assert len(attempted) == 1, f"expected exactly one attempt, got {attempted!r}"
    assert attempted[0]["status"] == JOB_QUEUED, "it should be back in the queue"
    assert attempted[0]["result_status"] == RESULT_MESSAGING_UNAVAILABLE
    requeued = attempted

    target = dict(await db.get_outreach_target(database, requeued[0]["target_id"]))
    assert target["status"] == TARGET_QUEUED
    # The account is not blamed for a target-side problem.
    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["consecutive_errors"] == 0


async def test_a_profile_that_does_not_exist_is_skipped_for_good(seeded, database):
    """The other side of the same rule, at the worker level.

    The site was asked and answered: there is no such account. Nothing is
    gained by asking again, so this one really is terminal — which is what
    keeps "retryable" from meaning "nothing is ever finished".
    """
    driver = MockMessenger(
        outcomes=[(RESULT_PROFILE_UNAVAILABLE, "this page isn't available")]
    )
    await _run(driver, seeded["settings"])

    jobs = [dict(j) for j in await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"]
    )]
    failed = [j for j in jobs if j["status"] == JOB_FAILED]
    assert len(failed) == 1
    target = dict(await db.get_outreach_target(database, failed[0]["target_id"]))
    assert target["status"] == TARGET_SKIPPED
    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["consecutive_errors"] == 0


async def test_an_expired_session_pauses_the_campaign_not_the_account(seeded, database):
    """Operator's rule: nothing pauses an account. The campaign waits, with
    the account named in the reason, and the target keeps its turn."""
    driver = MockMessenger(default=(RESULT_SESSION_EXPIRED, "login wall"))
    settings = seeded["settings"]
    assert await _run(driver, settings) is True

    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["status"] != ACCOUNT_PAUSED
    campaign = dict(await db.get_outreach_campaign(database, seeded["campaign"]["id"]))
    assert campaign["status"] == CAMPAIGN_PAUSED
    assert campaign["paused_until"] is None
    assert "login wall" in campaign["paused_reason"]
    assert seeded["account"]["name"] in campaign["paused_reason"]

    # Nothing runs while it waits, and the target was not spent.
    await _clear_backoff(database)
    assert await _run(driver, settings) is False
    jobs = [dict(j) for j in await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"])]
    assert not [j for j in jobs if j["status"] == JOB_FAILED]


async def test_a_phone_hiccup_retries_the_target_and_keeps_the_campaign_running(seeded, database):
    from services.outreach.constants import RESULT_DEVICE_UNAVAILABLE
    driver = MockMessenger(default=(RESULT_DEVICE_UNAVAILABLE, "TikTok did not come to the front"))
    await _run(driver, seeded["settings"])

    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["status"] != ACCOUNT_PAUSED
    campaign = dict(await db.get_outreach_campaign(database, seeded["campaign"]["id"]))
    assert campaign["status"] == CAMPAIGN_RUNNING
    jobs = [dict(j) for j in await db.get_outreach_jobs(
        database, campaign_id=seeded["campaign"]["id"])]
    held = [j for j in jobs if j["result_status"] == RESULT_DEVICE_UNAVAILABLE]
    assert len(held) == 1 and held[0]["status"] == JOB_QUEUED
    assert held[0]["run_after"] is not None


async def test_a_streak_of_phone_hiccups_rests_the_campaign_then_it_carries_on(seeded, database):
    from services.outreach.constants import RESULT_DEVICE_UNAVAILABLE
    driver = MockMessenger(default=(RESULT_DEVICE_UNAVAILABLE, "profile did not load"))
    for _ in range(runner.PHONE_STREAK):
        await _clear_backoff(database)
        await _run(driver, seeded["settings"])

    campaign = dict(await db.get_outreach_campaign(database, seeded["campaign"]["id"]))
    assert campaign["status"] == CAMPAIGN_PAUSED
    assert campaign["paused_until"] is not None  # resumes by itself
    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["status"] != ACCOUNT_PAUSED


async def test_a_success_between_hiccups_resets_the_streak(seeded, database):
    from services.outreach.constants import RESULT_DEVICE_UNAVAILABLE
    hiccup = (RESULT_DEVICE_UNAVAILABLE, "slow")
    driver = MockMessenger(outcomes=[hiccup, hiccup, "sent", hiccup, hiccup])
    for _ in range(5):
        await _clear_backoff(database)
        await _run(driver, seeded["settings"])
    campaign = dict(await db.get_outreach_campaign(database, seeded["campaign"]["id"]))
    assert campaign["status"] == CAMPAIGN_RUNNING


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


# --- several accounts at once ----------------------------------------------

class _Rendezvous(MockMessenger):
    """A driver that records how many sends were ever in flight together.

    Serial execution cannot get past the barrier — there is never a second
    arrival — so it waits out the timeout and reports a peak of one. That
    is the failure this is here to catch, and it fails on the number rather
    than on a hang.
    """

    def __init__(self, expected: int, **kwargs):
        super().__init__(**kwargs)
        self._barrier = asyncio.Barrier(expected)
        self._in_flight = 0
        self.peak_in_flight = 0
        self.accounts_seen: list[int] = []

    async def send_message(self, account, target, message):
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        self.accounts_seen.append(int(account["id"]))
        try:
            async with asyncio.timeout(3):
                await self._barrier.wait()
        except (TimeoutError, asyncio.BrokenBarrierError):
            pass
        finally:
            self._in_flight -= 1
        return await super().send_message(account, target, message)


async def test_two_accounts_can_send_at_the_same_time(
    seeded, database, account_factory
):
    """Two sends overlapping, on two accounts, through one worker.

    This was already true of `process_one` — it is the local worker's loop
    that serialised everything, and that is covered separately below. What
    this holds is the property that loop depends on: that two slots sharing
    a worker and a browser do not tread on each other, and that a lease
    hands them different accounts.

    Overlap is measured rather than assumed, because a serial worker sends
    both messages too and would pass any assertion about the results.
    """
    await account_factory(name="Sender 2")
    driver = _Rendezvous(expected=2)
    worker = runner.OutreachWorker(worker_id="local", driver=driver)
    settings = seeded["settings"]

    results = await asyncio.gather(
        worker.process_one(settings), worker.process_one(settings)
    )

    assert results == [True, True]
    assert driver.peak_in_flight == 2, (
        f"the two sends never overlapped (peak {driver.peak_in_flight}) — "
        f"the worker is still running them one after another"
    )
    assert len(set(driver.accounts_seen)) == 2, (
        f"both slots took the same account: {driver.accounts_seen}"
    )


async def test_a_second_slot_idles_when_only_one_account_is_free(seeded, database):
    """One account and two slots is not an error, it is a quiet slot.

    A lease is exclusive, so the second slot finds nothing to take and says
    so. It must not wait for the first, and it must not send from an
    account already in use.
    """
    driver = MockMessenger()
    worker = runner.OutreachWorker(worker_id="local", driver=driver)
    settings = seeded["settings"]

    results = await asyncio.gather(
        worker.process_one(settings), worker.process_one(settings)
    )

    assert sorted(results) == [False, True], f"expected one slot to idle: {results}"
    assert len(driver.sent) == 1


async def test_concurrent_slots_start_only_one_browser(monkeypatch):
    """Building the driver is check-then-await, which is a race.

    Both slots look for a driver, both find none, and both launch one — the
    second replaces the first in the registry and the first goes on running
    with nothing left holding a reference to close it. An orphaned headed
    Chromium is not subtle on a laptop.
    """
    built = []

    class _Slow:
        name = "mock"

        async def startup(self):
            # Long enough that a second caller arrives mid-launch, which is
            # exactly the window the bug lived in.
            await asyncio.sleep(0.05)
            built.append(self)

        async def shutdown(self):
            pass

    monkeypatch.setattr(runner, "get_driver", lambda name, **kw: _Slow())
    worker = runner.OutreachWorker(worker_id="local")
    settings = {runner.cfg.DRIVER_KEY: "mock", "outreach_worker_concurrency": 4}

    drivers = await asyncio.gather(*(
        worker._get_driver(settings) for _ in range(4)
    ))

    assert len(built) == 1, f"launched {len(built)} browsers, expected 1"
    assert len({id(d) for d in drivers}) == 1, "slots got different drivers"


async def test_the_local_worker_opens_a_window_per_configured_slot(monkeypatch):
    """The bug itself: the local sender ran one job at a time.

    `OutreachWorker.run()` has always spread work over N slots, but the Mac
    worker never used it — `_local_worker_loop` was its own `while True`
    around a single `process_one`, so `outreach_worker_concurrency` did
    nothing there and one Chromium window was open no matter how many
    accounts were connected.

    Nothing here opens a browser. What is being checked is arithmetic the
    old loop could not do: how many slots the loop starts.
    """
    started = 0
    forever = asyncio.Event()

    async def _fake_slot(_worker, _stopping):
        nonlocal started
        started += 1
        await forever.wait()

    class _StubWorker:
        async def apply_headless(self, headless):
            """The local sender asks this every tick."""
            self.headless = headless
        def __init__(self, *a, **kw):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setattr(runner, "_local_slot", _fake_slot)
    monkeypatch.setattr(runner, "OutreachWorker", _StubWorker)

    async def _settings(_db):
        return {"outreach_local_worker_concurrency": 3}

    monkeypatch.setattr(runner.cfg, "get_all", _settings)

    task = asyncio.create_task(runner._local_worker_loop())
    try:
        async with asyncio.timeout(3):
            while started < 3:
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert started == 3, f"started {started} slots, expected 3"
    assert runner.local_worker_state()["running"] is False, (
        "the loop must not leave itself marked running after it stops"
    )


# --- stopping without killing a send ---------------------------------------

async def test_a_shutdown_waits_for_a_send_already_in_flight(monkeypatch):
    """Cancelling the sender must not abandon a job halfway through.

    Restarting the API to deploy a change killed the worker between
    clicking Send and confirming it. The job stayed `processing` on a
    ten-minute lease, the account stayed `active` and unleasable for the
    same ten minutes, and the campaign stopped dead without saying why.
    The reaper does recover it — but the requeued target then had to be
    sent again with no way to know whether the first attempt had landed.

    So cancellation now means "finish this one, then stop".
    """
    started = asyncio.Event()
    release = asyncio.Event()
    finished = False

    async def _slow_slot(_worker, stopping):
        nonlocal finished
        started.set()
        await release.wait()          # the send, mid-flight
        finished = True               # the confirmation it must reach

    class _StubWorker:
        async def apply_headless(self, headless):
            """The local sender asks this every tick."""
            self.headless = headless
        def __init__(self, *a, **kw):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setattr(runner, "_local_slot", _slow_slot)
    monkeypatch.setattr(runner, "OutreachWorker", _StubWorker)

    async def _settings(_db):
        return {"outreach_local_worker_concurrency": 1}

    monkeypatch.setattr(runner.cfg, "get_all", _settings)

    task = asyncio.create_task(runner._local_worker_loop())
    async with asyncio.timeout(3):
        await started.wait()

    # The shutdown, exactly as the lifespan delivers it.
    stopper = asyncio.create_task(runner.stop_background_tasks([task]))
    await asyncio.sleep(0.05)
    assert not finished, "the send should still be running"
    assert not stopper.done(), "shutdown returned while a send was in flight"

    release.set()                      # the send completes
    async with asyncio.timeout(5):
        await stopper

    assert finished, "the shutdown abandoned a send instead of waiting for it"


async def test_a_send_that_never_finishes_does_not_hold_the_shutdown_open(
    monkeypatch
):
    """The wait is bounded. A deploy cannot hang on a stuck page.

    Past the bound the slot is cancelled and its job keeps its lease, which
    is the case the reaper already exists for — the same outcome as before,
    reached deliberately instead of by accident.
    """
    started = asyncio.Event()

    async def _stuck_slot(_worker, stopping):
        started.set()
        await asyncio.Event().wait()   # never returns

    class _StubWorker:
        async def apply_headless(self, headless):
            """The local sender asks this every tick."""
            self.headless = headless
        def __init__(self, *a, **kw):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setattr(runner, "_local_slot", _stuck_slot)
    monkeypatch.setattr(runner, "OutreachWorker", _StubWorker)
    monkeypatch.setattr(runner, "DRAIN_SECONDS", 1)

    async def _settings(_db):
        return {"outreach_local_worker_concurrency": 1}

    monkeypatch.setattr(runner.cfg, "get_all", _settings)

    task = asyncio.create_task(runner._local_worker_loop())
    async with asyncio.timeout(3):
        await started.wait()

    async with asyncio.timeout(20):
        await runner.stop_background_tasks([task])

    assert task.done(), "the stuck slot was left running after shutdown"


async def test_a_draining_slot_does_not_claim_another_job(monkeypatch):
    """Draining means finishing, not squeezing one more in."""
    claims = 0
    first_claim = asyncio.Event()

    class _CountingWorker:
        async def apply_headless(self, headless):
            """The local sender asks this every tick."""
            self.headless = headless
        def __init__(self, *a, **kw):
            pass

        async def process_one(self, settings):
            nonlocal claims
            claims += 1
            first_claim.set()
            await asyncio.sleep(0.05)
            return True

        async def shutdown(self):
            pass

    monkeypatch.setattr(runner, "OutreachWorker", _CountingWorker)

    async def _settings(_db):
        return {
            "outreach_local_worker_concurrency": 1,
            runner.cfg.WORKERS_ENABLED_KEY: True,
            "outreach_worker_idle_seconds": 1,
        }

    monkeypatch.setattr(runner.cfg, "get_all", _settings)

    task = asyncio.create_task(runner._local_worker_loop())
    async with asyncio.timeout(3):
        await first_claim.wait()

    await runner.stop_background_tasks([task])
    settled = claims
    await asyncio.sleep(0.2)
    assert claims == settled, (
        f"a slot claimed another job while draining ({settled} -> {claims})"
    )


async def test_a_shutdown_waits_for_an_open_sign_in_window(monkeypatch):
    """Stopping the API closes a sign-in window under whoever is typing.

    The capture is a task in this process holding a headed browser, so a
    restart takes the window with it — mid-password, with no explanation
    beyond "the window was closed before sign-in finished". Waiting is the
    least it can do, and saying so is the rest.
    """
    open_accounts = [9]

    monkeypatch.setattr(
        runner.session_capture, "running_accounts", lambda: list(open_accounts)
    )
    monkeypatch.setattr(
        runner.session_capture, "any_running", lambda: bool(open_accounts)
    )
    monkeypatch.setattr(runner, "DRAIN_SECONDS", 5)

    stopper = asyncio.create_task(runner.stop_background_tasks([]))
    await asyncio.sleep(1.5)
    assert not stopper.done(), "shutdown did not wait for the open sign-in"

    open_accounts.clear()                     # the person finishes signing in
    async with asyncio.timeout(5):
        await stopper


async def test_a_shutdown_is_not_delayed_when_nothing_is_signing_in(monkeypatch):
    """The wait is for a real window, not a tax on every restart."""
    monkeypatch.setattr(runner.session_capture, "running_accounts", lambda: [])
    monkeypatch.setattr(runner.session_capture, "any_running", lambda: False)
    monkeypatch.setattr(runner, "DRAIN_SECONDS", 30)

    started = asyncio.get_running_loop().time()
    await runner.stop_background_tasks([])
    assert asyncio.get_running_loop().time() - started < 2


# --- the browser survives between jobs -------------------------------------

class _CountingDriver(MockMessenger):
    """Records every release, so a test can see the churn."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.released: list[int] = []

    async def release_account(self, account_id):
        self.released.append(int(account_id))


async def test_the_browser_is_kept_between_jobs(seeded, database):
    """The logged-in browser used to be torn down after every target.

    A fresh context and a fresh tab per profile — several hundred times a
    run — with a window opening and closing each time on the visible
    worker. Nothing depended on it: no session is exported here, so the
    teardown preserved nothing and only cost.
    """
    driver = _CountingDriver()
    settings = seeded["settings"]

    await _run(driver, settings)
    await _clear_backoff(database)
    await _run(driver, settings)

    assert len(driver.sent) == 2, "both jobs should have run"
    assert driver.released == [], (
        f"the browser was thrown away between jobs: {driver.released}"
    )


async def test_the_browser_is_dropped_when_the_session_is_in_question(
    seeded, database
):
    """Kept is not the same as kept forever.

    An expired session means the logged-in browser is no longer worth
    trusting, and the account is paused anyway — whatever runs next should
    start from the stored session rather than inherit this one.
    """
    driver = _CountingDriver(outcomes=[(RESULT_SESSION_EXPIRED, "login wall")])
    await _run(driver, seeded["settings"])

    assert driver.released == [seeded["account"]["id"]], (
        f"expected the context to be dropped, got {driver.released}"
    )


async def test_an_ordinary_failure_keeps_the_browser(seeded, database):
    """A target with no Message button says nothing about our session."""
    driver = _CountingDriver(outcomes=[(RESULT_MESSAGING_UNAVAILABLE, "no DMs")])
    await _run(driver, seeded["settings"])

    assert driver.released == [], (
        f"a target-side failure threw the browser away: {driver.released}"
    )


# --- following as a campaign of its own ------------------------------------

async def test_a_follow_campaign_follows_and_never_messages(seeded, database):
    """A follow campaign is not a message campaign with an empty body.

    Following existed only as a step inside sending, so an account could be
    warmed up only by messaging someone. This is the whole activity on its
    own: the driver is asked to follow, nothing is typed, and the target is
    recorded exactly as a completed piece of work.
    """
    await db.update_outreach_campaign(
        database, seeded["campaign"]["id"], activity="follow")
    await database.session.commit()

    driver = MockMessenger()
    assert await _run(driver, seeded["settings"]) is True

    assert driver.sent == [], f"a follow campaign sent a message: {driver.sent!r}"
    assert len(driver.followed) == 1
    account_id, username = driver.followed[0]
    assert account_id == seeded["account"]["id"]

    target = next(
        t for t in await db.get_outreach_targets(database, seeded["campaign"]["id"])
        if t["username"] == username
    )
    assert target["status"] == TARGET_SENT


async def test_a_follow_campaign_does_not_need_a_message_template(seeded, database):
    """No template, no variables, nothing to render — and no failure.

    Rendering ran before the driver was chosen, so a campaign with an empty
    body would have failed every job on a template error before it ever got
    as far as following anybody.
    """
    await db.update_outreach_campaign(
        database, seeded["campaign"]["id"], activity="follow", message_template="")
    await database.session.commit()

    driver = MockMessenger()
    assert await _run(driver, seeded["settings"]) is True
    assert len(driver.followed) == 1
    assert driver.sent == []


async def test_closing_the_browser_does_not_stop_the_local_sender(monkeypatch):
    """Closing the window is not an off switch — the next job reopens it.

    The sender keeps claiming work; the driver simply has no browser for
    the moment, and opens one when something needs it. Requiring an API
    restart to send again is the behaviour this guards against.
    """
    lost: list = []
    claims = 0

    class _Worker:
        async def apply_headless(self, headless):
            """The local sender asks this every tick."""
            self.headless = headless
        def __init__(self, *a, on_browser_lost=None, **kw):
            lost.append(on_browser_lost)

        async def process_one(self, settings):
            nonlocal claims
            claims += 1
            return False  # nothing to claim, so the slot idles

        async def shutdown(self):
            pass

    monkeypatch.setattr(runner, "OutreachWorker", _Worker)

    async def _settings(_db):
        return {
            "outreach_local_worker_concurrency": 1,
            runner.cfg.WORKERS_ENABLED_KEY: True,
            "outreach_worker_idle_seconds": 1,
        }

    monkeypatch.setattr(runner.cfg, "get_all", _settings)

    task = asyncio.create_task(runner._local_worker_loop())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if lost and lost[0] is not None:
            break
    assert lost and lost[0] is not None, "no disconnect hook was given to the driver"

    lost[0]()  # exactly what Playwright does when the window is closed
    before = claims
    for _ in range(300):
        await asyncio.sleep(0.01)
        if claims > before:
            break

    assert claims > before, (
        "the sender stopped claiming work after the browser was closed — "
        "it should carry on and open a new one for the next job"
    )
    assert not task.done(), "the local sender exited when the window was closed"
    assert runner._LOCAL_WORKER["running"] is True

    await runner.stop_background_tasks([task])


# --- platform limits: the campaign waits, the account does not -------------

async def test_a_platform_limit_pauses_the_campaign_not_the_account(seeded, database):
    """A limit is a clock, and it belongs to the campaign.

    It used to count against the account's error budget and pause the
    *account* after five. That is the wrong unit twice: the account is
    healthy — it has done exactly as much as the platform allows — and
    pausing it stops every other campaign that account serves. A paused
    account also needs a person to un-pause it, so a limit that clears in
    hours cost a day.
    """
    driver = MockMessenger(default=(RESULT_FOLLOW_LIMITED, "follow limit reached"))
    settings = dict(seeded["settings"])
    await db.update_outreach_campaign(
        database, seeded["campaign"]["id"], activity="follow")

    assert await _run(driver, settings) is True

    account = dict(await db.get_sending_account(database, seeded["account"]["id"]))
    assert account["status"] in (ACCOUNT_IDLE, ACCOUNT_ACTIVE), (
        "the account was blamed for a limit it did not cause"
    )
    assert account["consecutive_errors"] == 0

    campaign = dict(await db.get_outreach_campaign(database, seeded["campaign"]["id"]))
    assert campaign["status"] == CAMPAIGN_PAUSED
    assert campaign["paused_until"] is not None
    assert "follow limit reached" in (campaign["paused_reason"] or ""), (
        "the platform's own words should be kept — our inference about a "
        "button that did not move is not what the operator needs to read"
    )


async def test_a_limited_job_keeps_its_retry_budget(seeded, database):
    """Waiting out a limit must not spend the target's attempts.

    The driver did what it was asked and the platform said "not now". If
    that counted as an attempt, a long enough limit would exhaust every
    target's retries without a single one having been refused.
    """
    driver = MockMessenger(default=(RESULT_FOLLOW_LIMITED, "follow limit reached"))
    settings = dict(seeded["settings"])
    await db.update_outreach_campaign(
        database, seeded["campaign"]["id"], activity="follow")
    await _run(driver, settings)

    rows = (await database.session.execute(
        text("SELECT status, attempts FROM outreach_jobs "
             " WHERE campaign_id = :cid AND status = :q"),
        {"cid": seeded["campaign"]["id"], "q": JOB_QUEUED},
    )).mappings().all()
    assert rows, "the job was not put back on the queue"
    assert all(r["attempts"] == 0 for r in rows), (
        f"a limit spent the retry budget: {[dict(r) for r in rows]}"
    )


async def test_a_campaign_resumes_itself_when_the_cooldown_expires(seeded, database):
    """The whole point of a deadline: nobody has to be watching."""
    campaign_id = seeded["campaign"]["id"]
    await database.session.execute(
        text("UPDATE outreach_campaigns "
             "   SET status = :paused, paused_until = (NOW() AT TIME ZONE 'UTC') "
             "       - INTERVAL '1 minute', paused_reason = 'follow limit reached' "
             " WHERE id = :cid"),
        {"cid": campaign_id, "paused": CAMPAIGN_PAUSED},
    )
    await database.session.commit()

    resumed = await job_queue.resume_limited_campaigns(database)
    assert campaign_id in resumed

    campaign = dict(await db.get_outreach_campaign(database, campaign_id))
    assert campaign["status"] == CAMPAIGN_RUNNING
    assert campaign["paused_until"] is None
    assert campaign["paused_reason"] is None


async def test_the_api_process_resumes_a_cooldown_too(seeded, database):
    """On a laptop the API process does the sending, and its maintenance
    used to skip this — campaign 15 sat "resuming" for fifteen hours."""
    campaign_id = seeded["campaign"]["id"]
    await database.session.execute(
        text("UPDATE outreach_campaigns "
             "   SET status = :paused, paused_until = (NOW() AT TIME ZONE 'UTC') "
             "       - INTERVAL '1 minute', paused_reason = 'phone break' "
             " WHERE id = :cid"),
        {"cid": campaign_id, "paused": CAMPAIGN_PAUSED},
    )
    await database.session.commit()

    await runner.maintenance_pass()

    campaign = dict(await db.get_outreach_campaign(database, campaign_id))
    assert campaign["status"] == CAMPAIGN_RUNNING


async def test_a_cooldown_that_has_not_expired_is_left_alone(seeded, database):
    campaign_id = seeded["campaign"]["id"]
    await database.session.execute(
        text("UPDATE outreach_campaigns "
             "   SET status = :paused, paused_until = (NOW() AT TIME ZONE 'UTC') "
             "       + INTERVAL '1 hour' WHERE id = :cid"),
        {"cid": campaign_id, "paused": CAMPAIGN_PAUSED},
    )
    await database.session.commit()
    assert await job_queue.resume_limited_campaigns(database) == []


async def test_an_operators_own_pause_is_never_resumed_by_the_clock(seeded, database):
    """A pause with no deadline was a decision, not a timer."""
    campaign_id = seeded["campaign"]["id"]
    await database.session.execute(
        text("UPDATE outreach_campaigns SET status = :paused, paused_until = NULL "
             " WHERE id = :cid"),
        {"cid": campaign_id, "paused": CAMPAIGN_PAUSED},
    )
    await database.session.commit()
    assert await job_queue.resume_limited_campaigns(database) == []
    campaign = dict(await db.get_outreach_campaign(database, campaign_id))
    assert campaign["status"] == CAMPAIGN_PAUSED


async def test_a_second_limit_does_not_push_the_deadline_out(seeded, database):
    """The first deadline wins, however many jobs land after it.

    The guard used to be an `if` on the campaign dict, which every slot
    read when it claimed its job — so each of them still said `running`
    and each wrote its own pause. The countdown crept forward while it was
    being watched. It is a condition on the UPDATE now.
    """
    campaign_id = seeded["campaign"]["id"]
    settings = dict(seeded["settings"])
    await db.update_outreach_campaign(database, campaign_id, activity="follow")

    driver = MockMessenger(default=(RESULT_FOLLOW_LIMITED, "follow limit reached"))
    assert await _run(driver, settings) is True
    first = dict(await db.get_outreach_campaign(database, campaign_id))
    assert first["status"] == CAMPAIGN_PAUSED
    deadline = first["paused_until"]
    assert deadline is not None

    # A second job lands holding the campaign as it was *before* the pause,
    # which is exactly what an in-flight slot has.
    stale = dict(first, status=CAMPAIGN_RUNNING, paused_until=None)
    worker = runner.OutreachWorker(worker_id="second-slot", driver=driver, once=True)
    await worker._pause_campaign_for_limit(
        database,
        stale,
        type("R", (), {"detail": {}, "error": "follow limit reached"})(),
        settings,
        900,
    )

    again = dict(await db.get_outreach_campaign(database, campaign_id))
    assert again["paused_until"] == deadline, (
        f"the deadline moved: {deadline} -> {again['paused_until']}"
    )


def test_the_limit_wait_is_not_a_setting():
    """One limit timer, and the admin page is not where it lives.

    There were briefly two things a person could read as the limit timer:
    the countdown on the campaign page, and three "wait this long before
    resuming" boxes on the admin page. They were never two timers — the
    boxes set the number the countdown counted down — but nothing on
    either page said so, and the obvious reading was that one of them was
    overriding the other. The wait is a constant now.
    """
    from services.outreach import config as cfg

    stale = {
        "outreach_follow_limit_cooldown_seconds": 900,
        "outreach_message_limit_cooldown_seconds": 900,
        "outreach_comment_limit_cooldown_seconds": 900,
    }
    for activity in ("follow", "message", "comment"):
        assert cfg.limit_cooldown_seconds(activity, stale) == 21_600, (
            f"{activity} still read its wait from settings"
        )

    # Rows for the old keys may linger in site_config on a live database.
    # Nothing reads them, and the admin page must not offer them back.
    for key in stale:
        assert key not in cfg.SPEC, f"{key} is still an editable setting"

    # And it still works with no settings dict at all, which is how the
    # runner will call it once nothing is threading settings through.
    assert cfg.limit_cooldown_seconds("follow") == 21_600
