"""Sending-account manager: leasing, caps, health and auto-pause."""
from __future__ import annotations

from sqlalchemy import text

import database as db
from services.outreach import accounts as account_mgr, importer, queue as job_queue
from services.outreach.constants import (
    ACCOUNT_ACTIVE,
    ACCOUNT_IDLE,
    ACCOUNT_PAUSED,
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


async def test_repeated_account_faults_auto_pause_with_a_reason(
    database, account_factory, settings
):
    account = await account_factory()
    threshold = int(settings["outreach_account_error_threshold"])
    for i in range(threshold):
        health = await account_mgr.record_failure(
            database, account["id"], RESULT_RATE_LIMITED, "slow down", settings
        )
        assert health["paused"] is (i == threshold - 1)

    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] == ACCOUNT_PAUSED
    assert "rate_limited" in row["paused_reason"]
    # The operator can see it — the pause is audited.
    audit = await db.get_outreach_audit_logs(
        database, entity_type="account", entity_id=account["id"]
    )
    assert any(a["action"] == "account.auto_paused" for a in audit)


async def test_an_expired_session_pauses_the_account_immediately(
    database, account_factory, settings
):
    """Retrying an expired session just burns attempts — pause at once."""
    account = await account_factory()
    health = await account_mgr.record_failure(
        database, account["id"], RESULT_SESSION_EXPIRED, "login wall", settings
    )
    assert health["paused"] is True
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] == ACCOUNT_PAUSED


async def test_a_paused_account_is_not_leased_again(
    database, campaign_factory, account_factory, settings
):
    campaign = await campaign_factory()
    account = await account_factory()
    await account_mgr.record_failure(
        database, account["id"], RESULT_SESSION_EXPIRED, "login wall", settings
    )
    await _age_activity(database, account["id"], minutes=120)
    assert await account_mgr.lease_account(database, campaign, settings) is None


async def test_resume_clears_the_pause(database, account_factory, settings):
    account = await account_factory()
    await account_mgr.record_failure(
        database, account["id"], RESULT_SESSION_EXPIRED, "login wall", settings
    )
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
    await account_mgr.record_failure(
        database, account["id"], RESULT_SESSION_EXPIRED, "login wall", settings
    )
    await account_mgr.release_account(database, account["id"])
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["status"] == ACCOUNT_PAUSED
