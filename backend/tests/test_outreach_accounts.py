"""Sending-account manager: leasing, caps, health and auto-pause."""
from __future__ import annotations

import os
import socket

from sqlalchemy import text

import database as db
from services.outreach import accounts as account_mgr, importer, queue as job_queue
from services.outreach.constants import (
    ACCOUNT_ACTIVE,
    ACCOUNT_FAULT_RESULTS,
    ACCOUNT_IDLE,
    ACCOUNT_PAUSED,
    LIMIT_RESULTS,
    RESULT_BROWSER_ERROR,
    RESULT_FOLLOW_LIMITED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SESSION_EXPIRED,
)


async def _age_activity(database, account_id: int, minutes: int = 60) -> None:
    """Backdate last_activity_at so cooldown/lease checks see an old value."""
    await database.session.execute(
        text(
            "UPDATE outreach_sending_accounts "
            "   SET last_activity_at = (NOW() AT TIME ZONE 'UTC') "
            f"                        - INTERVAL '{int(minutes)} minutes' "
            " WHERE id = :id"
        ),
        {"id": account_id},
    )
    await database.session.commit()


# --- eligibility -----------------------------------------------------------

async def test_no_assignment_means_every_enabled_account_on_the_platform(
    database, campaign_factory, account_factory
):
    campaign = await campaign_factory()
    first = await account_factory(name="A")
    second = await account_factory(name="B")
    assert set(await account_mgr.eligible_account_ids(database, campaign)) == {
        first["id"], second["id"]
    }


async def test_assignment_narrows_the_pool(database, campaign_factory, account_factory):
    campaign = await campaign_factory()
    first = await account_factory(name="A")
    await account_factory(name="B")
    await db.assign_account_to_campaign(database, campaign["id"], first["id"])
    assert await account_mgr.eligible_account_ids(database, campaign) == [first["id"]]


async def test_disabled_and_paused_accounts_are_not_eligible(
    database, campaign_factory, account_factory
):
    campaign = await campaign_factory()
    await account_factory(name="off", enabled=False)
    await account_factory(name="paused", status=ACCOUNT_PAUSED)
    live = await account_factory(name="ok")
    assert await account_mgr.eligible_account_ids(database, campaign) == [live["id"]]


async def test_accounts_for_another_platform_are_not_eligible(
    database, campaign_factory, account_factory
):
    campaign = await campaign_factory()
    await db.update_sending_account(
        database, (await account_factory(name="ig"))["id"], platform="instagram"
    )
    assert await account_mgr.eligible_account_ids(database, campaign) == []


# --- leasing ---------------------------------------------------------------

async def test_lease_takes_one_account_exclusively(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    await account_factory(name="only")

    leased = await account_mgr.lease_account(database, campaign, settings)
    assert leased is not None
    assert leased["status"] == ACCOUNT_ACTIVE

    # A second worker gets nothing — the only account is held.
    other = await db.get_db()
    try:
        assert await account_mgr.lease_account(other, campaign, settings) is None
    finally:
        await other.close()

    await account_mgr.release_account(database, leased["id"])
    assert (await account_mgr.lease_account(database, campaign, settings)) is not None


async def test_lease_spreads_work_across_accounts(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    first = await account_factory(name="A")
    second = await account_factory(name="B")

    a = await account_mgr.lease_account(database, campaign, settings)
    b = await account_mgr.lease_account(database, campaign, settings)
    assert {a["id"], b["id"]} == {first["id"], second["id"]}


async def test_a_disabled_account_is_never_leased(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    account = await account_factory(name="A")
    await db.update_sending_account(database, account["id"], enabled=False)
    assert await account_mgr.lease_account(database, campaign, settings) is None


async def test_the_send_cooldown_holds_an_account_back(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    await account_factory(name="A")
    throttled = dict(settings, outreach_min_send_interval_seconds=3600)

    leased = await account_mgr.lease_account(database, campaign, throttled)
    assert leased is not None
    await account_mgr.release_account(database, leased["id"])
    # Just used → inside the cooldown window.
    assert await account_mgr.lease_account(database, campaign, throttled) is None
    await _age_activity(database, leased["id"], minutes=120)
    assert await account_mgr.lease_account(database, campaign, throttled) is not None


async def test_an_expired_lease_frees_the_account(
    database, campaign_factory, account_factory, settings
):
    """A worker killed mid-job must not strand its account forever."""
    campaign = await campaign_factory()
    account = await account_factory(name="A")

    leased = await account_mgr.lease_account(database, campaign, settings)
    assert leased is not None
    assert await account_mgr.lease_account(database, campaign, settings) is None

    await _age_activity(database, account["id"], minutes=120)
    assert await account_mgr.lease_account(database, campaign, settings) is not None


async def test_release_expired_leases_resets_the_status(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    account = await account_factory(name="A")
    await account_mgr.lease_account(database, campaign, settings)
    await _age_activity(database, account["id"], minutes=120)

    assert await account_mgr.release_expired_leases(database, settings) == 1
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] == ACCOUNT_IDLE


async def test_per_account_job_cap_is_enforced(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory(max_jobs_per_account=1)
    account = await account_factory(name="A")
    await importer.import_targets(database, campaign["id"], "username\nalice\nbob\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    leased = await account_mgr.lease_account(database, campaign, settings)
    job = await job_queue.claim_job(
        database, campaign["id"], leased["id"], "w", settings
    )
    await job_queue.complete_job(database, job)
    await account_mgr.release_account(database, leased["id"])
    await _age_activity(database, account["id"], minutes=120)

    # One job already assigned, cap is one — nothing more for this account.
    assert await account_mgr.lease_account(database, campaign, settings) is None


# --- health ----------------------------------------------------------------

async def test_success_bumps_the_counter_and_clears_the_streak(
    database, account_factory, settings
):
    account = await account_factory()
    await account_mgr.record_failure(
        database, account["id"], RESULT_RATE_LIMITED, "slow down", settings
    )
    await account_mgr.record_success(database, account["id"])

    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["messages_processed"] == 1
    assert row["consecutive_errors"] == 0
    assert row["last_error"] is None
    assert row["last_activity_at"] is not None


async def test_a_target_side_failure_does_not_blame_the_account(
    database, account_factory, settings
):
    account = await account_factory()
    for _ in range(10):
        health = await account_mgr.record_failure(
            database, account["id"], RESULT_MESSAGING_UNAVAILABLE, "DMs closed", settings
        )
    assert health["paused"] is False
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["consecutive_errors"] == 0
    assert row["error_count"] == 10
    assert row["status"] != ACCOUNT_PAUSED


async def _pause(database, account_id: int, reason: str = "paused by hand") -> None:
    """Accounts are never auto-paused any more; a pause can only be put there."""
    await database.session.execute(text(
        "UPDATE outreach_sending_accounts SET status = :p, paused_reason = :r WHERE id = :id"
    ), {"id": account_id, "p": ACCOUNT_PAUSED, "r": reason})
    await database.session.commit()


async def test_repeated_account_faults_never_pause_the_account(
    database, account_factory, settings
):
    """Operator's rule: nothing pauses an account. The streak is still kept."""
    account = await account_factory()
    threshold = int(settings["outreach_account_error_threshold"])
    for _ in range(threshold + 2):
        health = await account_mgr.record_failure(
            database, account["id"], RESULT_BROWSER_ERROR, "chromium died", settings
        )
        assert health["paused"] is False
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] != ACCOUNT_PAUSED
    assert row["consecutive_errors"] == threshold + 2


async def test_an_expired_session_does_not_pause_the_account(
    database, account_factory, settings
):
    account = await account_factory()
    health = await account_mgr.record_failure(
        database, account["id"], RESULT_SESSION_EXPIRED, "login wall", settings
    )
    assert health["paused"] is False
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] != ACCOUNT_PAUSED


async def test_a_paused_account_is_not_leased_again(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    account = await account_factory()
    await _pause(database, account["id"])
    await _age_activity(database, account["id"], minutes=120)
    assert await account_mgr.lease_account(database, campaign, settings) is None


async def test_resume_clears_the_pause(database, account_factory, settings):
    account = await account_factory()
    await _pause(database, account["id"])
    await account_mgr.resume_account(database, account["id"])
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] == ACCOUNT_IDLE
    assert row["paused_reason"] is None
    assert row["consecutive_errors"] == 0


async def test_releasing_a_lease_never_unpauses_an_account(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    account = await account_factory()
    await account_mgr.lease_account(database, campaign, settings)
    await _pause(database, account["id"])
    await account_mgr.release_account(database, account["id"])
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] == ACCOUNT_PAUSED


# --- saying why, when nothing can be leased ---------------------------------

async def test_a_capped_account_explains_itself(
    database, campaign_factory, account_factory, settings
):
    """A campaign that cannot run has to say so.

    Both live campaigns stopped dead at exactly 100 targets and looked
    broken: the campaign said running, the accounts said idle with no
    errors, 862 jobs sat claimable, and nothing moved. The worker was
    asking for an account every ten seconds, being told no, and going
    quietly back to sleep — for over an hour, without one line of log.

    The cap doing that is correct. Being unable to find out is not.
    """
    campaign = await campaign_factory(max_jobs_per_account=1)
    account = await account_factory(name="Build a Brand")
    await importer.import_targets(database, campaign["id"], "username\nalice\nbob\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    leased = await account_mgr.lease_account(database, campaign, settings)
    job = await job_queue.claim_job(
        database, campaign["id"], leased["id"], "w", settings
    )
    await job_queue.complete_job(database, job)
    await account_mgr.release_account(database, leased["id"])
    await _age_activity(database, account["id"], minutes=120)

    assert await account_mgr.lease_account(database, campaign, settings) is None

    why = await account_mgr.explain_no_account(database, campaign, settings)
    assert why, "a campaign that cannot run has to be able to say why"
    assert "Build a Brand" in why, f"which account is stuck: {why!r}"
    assert "1 of its 1" in why, f"the numbers have to be in it: {why!r}"


async def test_the_explanation_separates_a_pause_from_a_cap(
    database, campaign_factory, account_factory, settings
):
    """Two reasons that need different things done about them.

    A capped account needs the cap raised or another account. A paused one
    needs whatever paused it fixed. Reporting either as "no account
    available" sends the operator looking in the wrong place.
    """
    campaign = await campaign_factory()
    account = await account_factory(name="Paused One")
    await database.session.execute(
        text(
            "UPDATE outreach_sending_accounts "
            "   SET status = :paused, paused_reason = :reason WHERE id = :id"
        ),
        {"id": account["id"], "paused": ACCOUNT_PAUSED, "reason": "session expired"},
    )
    await database.session.commit()

    assert await account_mgr.lease_account(database, campaign, settings) is None

    why = await account_mgr.explain_no_account(database, campaign, settings)
    assert "Paused One" in why and "paused" in why.lower(), why
    assert "of" not in why.split("paused")[-1], (
        f"a paused account should not be reported as a cap: {why!r}"
    )


async def test_a_lease_held_by_a_dead_worker_is_named(
    database, campaign_factory, account_factory, settings
):
    """The silence that cost ten minutes.

    Restarting the API killed a worker mid-job. Its account stayed `active`
    holding a ten-minute lease, so nothing could be leased and the campaign
    stopped — while the only thing logged was that a *different* account
    was paused. A busy account is not worth a line in the log; an account
    held by a process that no longer exists is the whole answer.

    The pid is checked rather than guessed, so this is exact for a worker
    on this machine and declines to speculate about any other.
    """
    campaign = await campaign_factory()
    account = await account_factory(name="Miahealth")
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    leased = await account_mgr.lease_account(database, campaign, settings)
    job = await job_queue.claim_job(
        database, campaign["id"], leased["id"], "w", settings
    )
    # A worker on this host whose pid is long gone. 2**22 is above every
    # configured pid_max, so it cannot collide with a live process.
    dead = f"{socket.gethostname()}:{2 ** 22}:abc123"
    await database.session.execute(
        text("UPDATE outreach_jobs SET worker_id = :w WHERE id = :i"),
        {"w": dead, "i": job["id"]},
    )
    await database.session.commit()

    assert await account_mgr.lease_account(database, campaign, settings) is None

    why = await account_mgr.explain_no_account(database, campaign, settings)
    assert "Miahealth" in why, why
    assert "no longer running" in why, why


async def test_an_account_genuinely_mid_send_is_not_reported(
    database, campaign_factory, account_factory, settings
):
    """Busy is the normal shape of a working system.

    The same query, the same `active` status, the same held lease — and
    nothing to tell anyone, because it clears itself in seconds. Reporting
    it would put a line in the log every ten minutes of every healthy run,
    which is how a useful message becomes one nobody reads.
    """
    campaign = await campaign_factory()
    account = await account_factory(name="Busy One")
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    leased = await account_mgr.lease_account(database, campaign, settings)
    job = await job_queue.claim_job(
        database, campaign["id"], leased["id"], "w", settings
    )
    # This process, which is very much alive.
    alive = f"{socket.gethostname()}:{os.getpid()}:abc123"
    await database.session.execute(
        text("UPDATE outreach_jobs SET worker_id = :w WHERE id = :i"),
        {"w": alive, "i": job["id"]},
    )
    await database.session.commit()

    why = await account_mgr.explain_no_account(database, campaign, settings)
    assert why == "", f"a working send should say nothing, got {why!r}"


def test_a_lease_from_another_machine_is_never_declared_dead():
    """A pid on another host means nothing here.

    Two senders handed the same target is a worse outcome than a slow
    recovery, and lease expiry already covers the remote case.
    """
    assert account_mgr.worker_is_gone(f"some-other-host:{2 ** 22}:abc") is False
    assert account_mgr.worker_is_gone(None) is False
    assert account_mgr.worker_is_gone("malformed") is False
    assert account_mgr.worker_is_gone(f"{socket.gethostname()}:notapid:x") is False


async def test_a_platform_limit_is_not_the_accounts_fault(
    database, account_factory, settings
):
    """Limits are a clock, and the clock is the campaign's to wait out.

    `rate_limited` and `follow_limited` used to sit in ACCOUNT_FAULT_RESULTS
    and pause the account after five. The account is healthy — it has done
    exactly as much as the platform allows — and pausing it stops every
    other campaign that account serves, for a fault it does not have. Worse,
    a paused account waits for a person, so a limit that cleared in hours
    cost a day.
    """
    account = await account_factory()
    threshold = int(settings["outreach_account_error_threshold"])
    for status in (RESULT_RATE_LIMITED, RESULT_FOLLOW_LIMITED):
        assert status in LIMIT_RESULTS
        assert status not in ACCOUNT_FAULT_RESULTS

    for _ in range(threshold + 2):
        health = await account_mgr.record_failure(
            database, account["id"], RESULT_FOLLOW_LIMITED,
            "follow limit reached", settings,
        )
        assert health["paused"] is False

    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] != ACCOUNT_PAUSED
    assert row["consecutive_errors"] == 0, (
        "a limit spent the account's error budget — five of them in a row "
        "would pause an account that is working perfectly"
    )


async def test_a_busy_day_no_longer_stops_an_account(
    database, campaign_factory, account_factory, settings
):
    """There is no daily action ceiling of our own any more.

    There was one, and it was a number we picked. It stopped a healthy
    account for hours while the campaign still read "running" and nothing
    on the page said why — the account had simply done more today than we
    had guessed it should. Instagram's own limit arrives as a result the
    driver can see, pauses the campaign, and shows a countdown; a private
    counter in our database can do none of that and only ever guesses.

    So a settings dict still carrying the old key must change nothing.
    """
    campaign = await campaign_factory()
    account = await account_factory(name="Worked hard today")
    await importer.import_targets(
        database, campaign["id"], "username\nalice\nbob\ncarol\n")
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))

    # Three actions banked in the last hour, and an old cap of one.
    await database.session.execute(
        text(
            "INSERT INTO outreach_jobs "
            "  (campaign_id, target_id, sending_account_id, status, attempts, "
            "   completed_at, result_status, created_at, updated_at) "
            "SELECT :cid, t.id, :aid, 'succeeded', 1, "
            "       (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour', 'sent', "
            "       (NOW() AT TIME ZONE 'UTC'), (NOW() AT TIME ZONE 'UTC') "
            "  FROM outreach_targets t WHERE t.campaign_id = :cid LIMIT 3"
        ),
        {"cid": campaign["id"], "aid": account["id"]},
    )
    await database.session.commit()
    await _age_activity(database, account["id"], minutes=120)

    stale = dict(settings)
    stale["outreach_daily_action_cap"] = 1

    leased = await account_mgr.lease_account(database, campaign, stale)
    assert leased is not None, (
        "a day's work stopped the account — the daily cap is back"
    )
    assert leased["id"] == account["id"]

    why = await account_mgr.explain_no_account(database, campaign, stale)
    assert "24 hours" not in why, f"the cap is still being explained: {why!r}"
