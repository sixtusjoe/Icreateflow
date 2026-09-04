"""Sending-account manager.

Owns three things the queue deliberately does not:

* **Eligibility** — which accounts a campaign may use right now (enabled,
  not auto-paused, right platform, assigned to the campaign, under its
  per-account job cap, past its send-interval cooldown).
* **Mutual exclusion** — an account is leased to exactly one worker at a
  time. Two workers driving one TikTok session concurrently is how you get
  an account flagged, so the lease is taken in the database, not in
  process memory.
* **Health** — success and failure bookkeeping, and the auto-pause rule:
  once an account trips the consecutive-error threshold it is paused with
  a reason rather than retried forever.

The lease reuses the columns the spec already defines: `status='active'`
plus `last_activity_at`. A lease is considered expired once
`last_activity_at` is older than the job lease, so a killed worker's
accounts return to the pool on their own.

All timestamps go in as `NOW() AT TIME ZONE 'UTC'` — the columns are
`TIMESTAMP WITHOUT TIME ZONE` holding UTC, and a bare `NOW()` would write
the database server's local time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

import database as db
from services.outreach import config as cfg
from services.outreach.constants import (
    ACCOUNT_ACTIVE,
    ACCOUNT_IDLE,
    ACCOUNT_PAUSED,
    ACCOUNT_FAULT_RESULTS,
    AUDIT_ACCOUNT_AUTO_PAUSED,
    IMMEDIATE_ACCOUNT_PAUSE_RESULTS,
)

#: UTC "now" as a naive timestamp, in SQL.
UTC_NOW = "(NOW() AT TIME ZONE 'UTC')"


def utc_now() -> datetime:
    """UTC now, tz-naive — the convention for TIMESTAMP columns here."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def eligible_account_ids(database, campaign: dict) -> list[int]:
    """Accounts this campaign is allowed to send from, ignoring leases.

    An empty assignment list means "any enabled account on this platform";
    explicit assignments narrow it. Used by the dashboard and by the
    preflight check that refuses to start a campaign with no sender.
    """
    assigned = await db.get_campaign_account_ids(database, campaign["id"])
    rows = await db.get_sending_accounts(
        database, user_id=campaign.get("user_id"), platform=campaign.get("platform")
    )
    out = []
    for row in rows:
        if assigned and row["id"] not in assigned:
            continue
        if not row.get("enabled"):
            continue
        if row.get("status") == ACCOUNT_PAUSED:
            continue
        out.append(int(row["id"]))
    return out


async def lease_account(
    database, campaign: dict, settings: dict[str, Any]
) -> Optional[dict]:
    """Take an exclusive lease on one eligible account, or return None.

    Picks the least-recently-active eligible account so work spreads
    evenly instead of hammering account #1. The whole selection happens in
    one statement with `FOR UPDATE … SKIP LOCKED`, so two workers racing
    for the last free account cannot both win it.
    """
    lease_seconds = int(settings["outreach_job_lease_seconds"])
    cooldown = int(settings["outreach_min_send_interval_seconds"])
    per_account_cap = cfg.campaign_limit(
        campaign, settings, "max_jobs_per_account", "outreach_max_jobs_per_account"
    )
    assigned = await db.get_campaign_account_ids(database, campaign["id"])

    params: dict[str, Any] = {
        "platform": campaign.get("platform") or "tiktok",
        "campaign_id": campaign["id"],
        "lease": lease_seconds,
        "cooldown": cooldown,
        "cap": per_account_cap,
        "active": ACCOUNT_ACTIVE,
        "paused": ACCOUNT_PAUSED,
    }
    # Clauses are composed from a fixed vocabulary; every value is bound.
    owner_clause = ""
    if campaign.get("user_id") is not None:
        owner_clause = "AND a.user_id = :user_id"
        params["user_id"] = campaign["user_id"]

    assignment_clause = ""
    if assigned:
        keys = []
        for i, account_id in enumerate(assigned):
            key = f"aid{i}"
            params[key] = account_id
            keys.append(f":{key}")
        assignment_clause = f"AND a.id IN ({', '.join(keys)})"

    sql = f"""
        UPDATE outreach_sending_accounts
           SET status = :active, last_activity_at = {UTC_NOW}, updated_at = {UTC_NOW}
         WHERE id = (
               SELECT a.id
                 FROM outreach_sending_accounts a
                WHERE a.platform = :platform
                  AND a.enabled = TRUE
                  AND a.status <> :paused
                  {owner_clause}
                  {assignment_clause}
                  -- free, or its lease has expired (worker crash)
                  AND (a.status <> :active
                       OR a.last_activity_at IS NULL
                       OR a.last_activity_at < {UTC_NOW} - (:lease * INTERVAL '1 second'))
                  -- per-account send cooldown
                  AND (a.last_activity_at IS NULL
                       OR a.last_activity_at < {UTC_NOW} - (:cooldown * INTERVAL '1 second'))
                  -- per-account job cap for this campaign
                  AND (
                        SELECT COUNT(*) FROM outreach_jobs j
                         WHERE j.campaign_id = :campaign_id
                           AND j.sending_account_id = a.id
                           AND j.status <> 'cancelled'
                      ) < :cap
                ORDER BY a.last_activity_at ASC NULLS FIRST, a.id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
         )
        RETURNING *
    """
    session = database.session
    row = (await session.execute(text(sql), params)).mappings().first()
    await session.commit()
    return dict(row) if row else None


async def release_account(database, account_id: int, status: str = ACCOUNT_IDLE) -> None:
    """Drop the lease. Never clears an auto-pause."""
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_sending_accounts "
            f"   SET status = :status, updated_at = {UTC_NOW} "
            f" WHERE id = :id AND status = :active"
        ),
        {"id": account_id, "status": status, "active": ACCOUNT_ACTIVE},
    )
    await session.commit()


async def record_success(database, account_id: int) -> None:
    """One delivered message: bump the counter, clear the error streak."""
    session = database.session
    await session.execute(
        text(
            f"UPDATE outreach_sending_accounts "
            f"   SET messages_processed = messages_processed + 1, "
            f"       consecutive_errors = 0, "
            f"       last_error = NULL, "
            f"       last_activity_at = {UTC_NOW}, "
            f"       status = CASE WHEN status = :paused THEN status ELSE :idle END, "
            f"       updated_at = {UTC_NOW} "
            f" WHERE id = :id"
        ),
        {"id": account_id, "idle": ACCOUNT_IDLE, "paused": ACCOUNT_PAUSED},
    )
    await session.commit()


async def record_failure(
    database,
    account_id: int,
    result_status: str,
    error: Optional[str],
    settings: dict[str, Any],
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Record a failed attempt and apply the auto-pause rule.

    Only account-fault results (expired session, rate limit, browser
    crash) count toward the streak — a target with DMs closed must not
    burn the account's error budget.

    Returns `{"paused": bool, "reason": str | None, "consecutive_errors": int}`.
    """
    account_fault = result_status in ACCOUNT_FAULT_RESULTS
    threshold = int(settings["outreach_account_error_threshold"])
    session = database.session

    row = (await session.execute(
        text(
            f"UPDATE outreach_sending_accounts "
            f"   SET error_count = error_count + 1, "
            f"       consecutive_errors = CASE WHEN :fault THEN consecutive_errors + 1 "
            f"                                 ELSE consecutive_errors END, "
            f"       last_error = :error, "
            f"       last_activity_at = {UTC_NOW}, "
            f"       updated_at = {UTC_NOW} "
            f" WHERE id = :id "
            f"RETURNING consecutive_errors"
        ),
        {"id": account_id, "fault": account_fault, "error": (error or result_status)[:2000]},
    )).first()
    await session.commit()
    if not row:
        return {"paused": False, "reason": None, "consecutive_errors": 0}

    streak = int(row[0] or 0)
    should_pause = account_fault and (
        result_status in IMMEDIATE_ACCOUNT_PAUSE_RESULTS or streak >= threshold
    )
    if not should_pause:
        return {"paused": False, "reason": None, "consecutive_errors": streak}

    reason = (
        f"Auto-paused after {streak} consecutive {result_status} error(s): "
        f"{(error or result_status)[:300]}"
    )
    await session.execute(
        text(
            f"UPDATE outreach_sending_accounts "
            f"   SET status = :paused, paused_reason = :reason, updated_at = {UTC_NOW} "
            f" WHERE id = :id"
        ),
        {"id": account_id, "paused": ACCOUNT_PAUSED, "reason": reason},
    )
    await session.commit()
    await db.log_outreach_audit(
        database, AUDIT_ACCOUNT_AUTO_PAUSED, "account", account_id,
        user_id=user_id, detail=reason,
    )
    await db.log_error(
        database, "outreach.account", reason, user_id=user_id,
        context=f"account_id={account_id}", level="warning",
    )
    return {"paused": True, "reason": reason, "consecutive_errors": streak}


async def resume_account(database, account_id: int) -> None:
    """Clear an auto-pause so the account can be picked again."""
    await db.update_sending_account(
        database, account_id, status=ACCOUNT_IDLE, paused_reason=None, consecutive_errors=0
    )


async def release_expired_leases(database, settings: dict[str, Any]) -> int:
    """Return accounts whose worker died mid-job to the pool.

    Belt-and-braces: `lease_account` already treats an expired lease as
    free. This keeps the dashboard from showing a permanently "active"
    account after a crash.
    """
    lease_seconds = int(settings["outreach_job_lease_seconds"])
    session = database.session
    rows = (await session.execute(
        text(
            f"UPDATE outreach_sending_accounts "
            f"   SET status = :idle, updated_at = {UTC_NOW} "
            f" WHERE status = :active "
            f"   AND (last_activity_at IS NULL "
            f"        OR last_activity_at < {UTC_NOW} - (:lease * INTERVAL '1 second')) "
            f"RETURNING id"
        ),
        {"idle": ACCOUNT_IDLE, "active": ACCOUNT_ACTIVE, "lease": lease_seconds},
    )).all()
    await session.commit()
    return len(rows)
