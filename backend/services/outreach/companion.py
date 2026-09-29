"""TikTok follows done by the ICREATEFLOW phone app, with no cable.

TikTok web accepts a follow and discards it; the TikTok app keeps it
(memory.md, "TikTok follows go through a phone"). The cabled route drives
a phone over adb from the worker's machine. This one reverses the
direction: the phone app asks the server for follows and reports back, so
the phone can be anywhere with a connection — the user's own phone, in the
user's own location.

The worker and the API are separate processes, and the phone only ever
talks to the API, so a follow crosses between them as a row in
`outreach_companion_tasks`:

    worker  relay()   → INSERT pending, wait
    phone   claim()   → pending → claimed   (POST /companion/next)
    phone   finish()  → claimed → done      (POST /companion/tasks/{id}/result)
    worker            ← reads done, returns the phone's MessageResult

Everything around the follow — which account, pacing, limits, pauses,
audits — is the runner's, exactly as for every other driver. This module
only carries the follow there and the answer back.

Only the worker gives up on a task, and only by expiring a row that is
still `pending`, in one statement: a phone that claims at the same moment
either wins (and the worker keeps waiting) or finds nothing to claim. A
follow is never done twice and never done unreported.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from sqlalchemy import text

from services.outreach.browser import MessageResult
from services.outreach.constants import (
    ACCOUNT_VIA_BROWSER,
    ACCOUNT_VIA_PHONE,
    PHONE_PLATFORMS,
    RESULT_ALREADY_FOLLOWING,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_DEVICE_UNAVAILABLE,
    RESULT_FOLLOW_DISCARDED,
    RESULT_FOLLOW_LIMITED,
    RESULT_FOLLOW_REQUESTED,
    RESULT_MESSAGE_REFUSED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_NOT_FOLLOWING,
    RESULT_OUTCOME_UNKNOWN,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SENT,
    RESULT_UNEXPECTED_PAGE,
    RESULT_UNKNOWN,
)

UTC_NOW = "(NOW() AT TIME ZONE 'UTC')"

TASK_PENDING = "pending"
TASK_CLAIMED = "claimed"
TASK_DONE = "done"
TASK_EXPIRED = "expired"

ACTION_FOLLOW = "follow"
ACTION_MESSAGE = "message"
ACTION_UNFOLLOW = "unfollow"

#: How long a follow waits for the phone to pick it up. The app asks every
#: few seconds while it is taking jobs, so a phone that has not asked in
#: this long is off, asleep, or out of signal.
PICKUP_S = 90.0
#: How long a claimed follow may take. The phone checks who TikTok is
#: signed in as, opens the profile, taps, waits and reopens: well under a
#: minute normally, and a slow profile load is 20s on its own.
RUN_S = 180.0
POLL_S = 1.0
#: How stale "last seen" may get before a phone's request refreshes it.
SEEN_EVERY_S = 30

#: What a phone may report. Anything else is refused at the API rather
#: than handed to the runner, which routes pauses and cooldowns by status.
SUCCESS_RESULTS = frozenset({
    RESULT_SENT,
    RESULT_NOT_FOLLOWING,  # an unfollow that found nothing to undo
    RESULT_ALREADY_FOLLOWING,
    RESULT_FOLLOW_REQUESTED,
})
FAILURE_RESULTS = frozenset({
    RESULT_FOLLOW_DISCARDED,
    RESULT_FOLLOW_LIMITED,
    RESULT_DEVICE_UNAVAILABLE,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_UNEXPECTED_PAGE,
    # Messages: TikTok refused the wording (stops the campaign, see
    # CAMPAIGN_STOP_RESULTS), or said to slow down (a limit, with a clock).
    RESULT_MESSAGE_REFUSED,
    RESULT_RATE_LIMITED,
})
PHONE_RESULTS = SUCCESS_RESULTS | FAILURE_RESULTS


def uses_phone_app(account: dict) -> bool:
    """Whether this account's TikTok follows go to the phone app."""
    return (
        (account.get("platform") or "").strip().lower() in PHONE_PLATFORMS
        and (account.get("via") or ACCOUNT_VIA_BROWSER) == ACCOUNT_VIA_PHONE
    )


async def relay(database, account: dict, job: Optional[dict], target: dict,
                action: str = ACTION_FOLLOW, message: Optional[str] = None) -> MessageResult:
    """Hand one follow or message to the account's phone and wait for its answer.

    A message arrives already rendered — the phone types exactly what the
    campaign would have sent from the browser, and never sees a template.
    """
    if action == ACTION_MESSAGE and not (message or "").strip():
        return MessageResult.failure(RESULT_UNKNOWN, "Nothing to send — the message rendered empty")
    session = database.session
    device = (account.get("companion_device") or "").strip()
    handle = (account.get("device_handle") or "").strip().lstrip("@")
    if not device:
        return MessageResult.failure(
            RESULT_DEVICE_UNAVAILABLE,
            "This account is switched to phone, but no phone has linked it yet — open the "
            "ICREATEFLOW app, Phone tab, and link it — its follows wait until then")
    if not handle:
        return MessageResult.failure(
            RESULT_DEVICE_UNAVAILABLE,
            "The phone is linked but has no TikTok handle to check — link it again from the app")

    row = (await session.execute(text(
        "INSERT INTO outreach_companion_tasks "
        "  (account_id, device_id, job_id, action, username, handle, message, status) "
        "VALUES (:a, :d, :j, :act, :u, :h, :msg, :pending) RETURNING id"
    ), {
        "msg": message if action == ACTION_MESSAGE else None,
        "a": int(account["id"]), "d": device,
        "j": int(job["id"]) if job else None, "act": action,
        "u": target["username"], "h": handle, "pending": TASK_PENDING,
    })).first()
    await session.commit()
    task_id = int(row[0])

    pickup_by = time.monotonic() + PICKUP_S
    finish_by: Optional[float] = None
    while True:
        await asyncio.sleep(POLL_S)
        state = (await session.execute(text(
            "SELECT status, result_status, result_error, result_detail "
            "  FROM outreach_companion_tasks WHERE id = :id"
        ), {"id": task_id})).first()
        # Nothing else happens on this connection while the phone works,
        # and an open transaction held for minutes pins old row versions.
        await session.commit()
        if state is None:
            return MessageResult.failure(RESULT_UNKNOWN, "The phone's task disappeared")
        status = state[0]
        if status == TASK_DONE:
            return _result_of(state[1], state[2], state[3])
        now = time.monotonic()
        if status == TASK_CLAIMED:
            if finish_by is None:
                finish_by = now + RUN_S
            if now >= finish_by:
                if not await _expire(session, task_id, TASK_CLAIMED):
                    continue  # the answer landed in the same instant: read it
                if action == ACTION_MESSAGE:
                    # It may have gone out. A retry could send it twice; a
                    # follow retried only finds "already following".
                    return MessageResult.failure(
                        RESULT_OUTCOME_UNKNOWN,
                        "The phone took this message but never said whether it went out — "
                        "not retried, so nobody gets it twice",
                        task_id=task_id)
                return MessageResult.failure(
                    RESULT_DEVICE_UNAVAILABLE,
                    "The phone took the follow but never reported back — check the "
                    "ICREATEFLOW app on the phone — the follow will be tried again",
                    task_id=task_id)
            continue
        if now >= pickup_by:
            if await _expire(session, task_id, TASK_PENDING):
                return MessageResult.failure(
                    RESULT_DEVICE_UNAVAILABLE,
                    "The phone didn't pick up the follow — open ICREATEFLOW on the phone, "
                    "switch on Take follows — the follow will be tried again",
                    task_id=task_id)
            # The phone claimed it in the same instant: keep waiting.


async def _expire(session, task_id: int, expected: str) -> bool:
    """Give up on a task still in `expected` state. False if it moved on."""
    row = (await session.execute(text(
        f"UPDATE outreach_companion_tasks SET status = :expired, finished_at = {UTC_NOW} "
        f" WHERE id = :id AND status = :expected RETURNING id"
    ), {"id": task_id, "expired": TASK_EXPIRED, "expected": expected})).first()
    await session.commit()
    return row is not None


def _result_of(status: Optional[str], error: Optional[str],
               detail_json: Optional[str]) -> MessageResult:
    try:
        detail = json.loads(detail_json) if detail_json else {}
    except ValueError:
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    detail["via"] = "phone_app"
    if status in SUCCESS_RESULTS:
        return MessageResult(success=True, status=status, detail=detail)
    if status in FAILURE_RESULTS:
        return MessageResult.failure(status, error or status, **detail)
    return MessageResult.failure(RESULT_UNKNOWN, f"The phone reported {status!r}", **detail)


async def claim(database, device_id: str, user_id: Optional[int]) -> Optional[dict]:
    """The oldest pending follow for this phone, now claimed by it.

    `user_id` None is an admin, who may work any account's tasks — the
    same scope every other outreach endpoint uses. Also records that the
    phone was seen, whether or not there was work.
    """
    session = database.session
    scope = "" if user_id is None else " AND a.user_id = :uid"
    params: dict[str, Any] = {"dev": device_id, "pending": TASK_PENDING,
                              "claimed": TASK_CLAIMED}
    if user_id is not None:
        params["uid"] = user_id
    # At most every SEEN_EVERY_S: writing it locks the account row, and the
    # worker leases accounts with SKIP LOCKED — a phone asking every few
    # seconds would otherwise make the worker skip its account now and then.
    await session.execute(text(
        f"UPDATE outreach_sending_accounts a SET companion_seen_at = {UTC_NOW} "
        f" WHERE a.companion_device = :dev{scope} "
        f"   AND (a.companion_seen_at IS NULL "
        f"        OR a.companion_seen_at < {UTC_NOW} - (:every * INTERVAL '1 second'))"
    ), {**params, "every": SEEN_EVERY_S})
    row = (await session.execute(text(
        f"UPDATE outreach_companion_tasks SET status = :claimed, claimed_at = {UTC_NOW} "
        f" WHERE id = ("
        f"   SELECT t.id FROM outreach_companion_tasks t "
        f"     JOIN outreach_sending_accounts a ON a.id = t.account_id "
        f"    WHERE t.status = :pending AND t.device_id = :dev{scope} "
        # The task's device must still be the account's: unlinking a phone
        # takes back anything it had not yet picked up.
        f"      AND a.companion_device = t.device_id "
        f"    ORDER BY t.id LIMIT 1 FOR UPDATE OF t SKIP LOCKED) "
        f" RETURNING id, action, username, handle, message"
    ), params)).first()
    await session.commit()
    if row is None:
        return None
    return {"id": int(row[0]), "action": row[1], "username": row[2], "handle": row[3],
            "message": row[4]}


async def finish(database, task_id: int, device_id: str, status: str,
                 error: Optional[str], detail: Optional[dict]) -> bool:
    """Record the phone's answer. False unless this phone holds the task."""
    if status not in PHONE_RESULTS:
        raise ValueError(f"Unknown result {status!r}")
    session = database.session
    row = (await session.execute(text(
        f"UPDATE outreach_companion_tasks "
        f"   SET status = :done, result_status = :rs, result_error = :re, "
        f"       result_detail = :rd, finished_at = {UTC_NOW} "
        f" WHERE id = :id AND device_id = :dev AND status = :claimed RETURNING id"
    ), {
        "id": task_id, "dev": device_id, "done": TASK_DONE, "claimed": TASK_CLAIMED,
        "rs": status, "re": (error or None) and error[:500],
        "rd": json.dumps(detail or {})[:4000],
    })).first()
    await session.commit()
    return row is not None
