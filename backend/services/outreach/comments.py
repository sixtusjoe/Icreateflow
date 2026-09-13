"""Mass commenting: one video, many accounts, a comment each.

A comment campaign has no list of people. It has a video, a number of
comments to leave, and the lines to choose between — so its targets are
comment *slots*, one row per comment asked for. Everything the queue
already does for a message campaign then applies unchanged: leases,
per-account caps, send intervals, retries, the progress counters.

The lines matter more than they look. Several accounts posting the same
sentence under one video is the pattern a spam filter is built to catch,
so a campaign carries a set and each comment draws from it.
"""
from __future__ import annotations

import json
import random
from typing import Any, Optional, Sequence

from sqlalchemy import text

from services.outreach.constants import (
    ACTIVITY_COMMENT,
    ACTIVITY_MESSAGE,
    TARGET_QUEUED,
)

UTC_NOW = "(NOW() AT TIME ZONE 'UTC')"

#: Slot names. Unique within a campaign, which the targets table requires,
#: and legible in the UI — "comment 7" says what the row is.
SLOT_PREFIX = "comment "

#: A ceiling, not a recommendation. Hundreds of comments from a handful of
#: accounts on one video is not subtle, whatever the interval.
MAX_COMMENTS = 500


class CommentSetupError(ValueError):
    """The campaign cannot run as a comment campaign as written."""


def is_comment(campaign: dict[str, Any]) -> bool:
    return (campaign.get("activity") or ACTIVITY_MESSAGE) == ACTIVITY_COMMENT


def slot_name(index: int) -> str:
    return f"{SLOT_PREFIX}{index}"


def variations(campaign: dict[str, Any]) -> list[str]:
    """The lines a comment may use.

    Stored as a JSON array. A campaign written before this existed, or one
    whose lines were cleared, falls back to the message box so that the
    campaign still has something to say rather than failing every job.
    """
    raw = campaign.get("comment_variations")
    lines: list[str] = []
    if raw:
        try:
            loaded = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            loaded = None
        if isinstance(loaded, list):
            lines = [str(x).strip() for x in loaded if str(x).strip()]
        elif isinstance(loaded, str):
            lines = [line.strip() for line in loaded.splitlines() if line.strip()]
    if not lines:
        fallback = (campaign.get("message_template") or "").strip()
        lines = [line.strip() for line in fallback.splitlines() if line.strip()]
    return lines


def pick(lines: Sequence[str], rng: Optional[random.Random] = None) -> str:
    """One line, chosen at random.

    Random rather than round-robin on purpose: round-robin over a short
    list makes the order itself a pattern when several accounts run at
    once.
    """
    if not lines:
        raise CommentSetupError("This campaign has no comment lines to post.")
    return (rng or random).choice(list(lines))


def validate(campaign: dict[str, Any]) -> None:
    """Refuse a comment campaign that cannot do anything useful."""
    if not (campaign.get("target_url") or "").strip():
        raise CommentSetupError(
            "A comment campaign needs the video to comment on."
        )
    count = int(campaign.get("comment_count") or 0)
    if count < 1:
        raise CommentSetupError("Ask for at least one comment.")
    if count > MAX_COMMENTS:
        raise CommentSetupError(
            f"{count} comments is more than this will post on one video "
            f"(the limit is {MAX_COMMENTS})."
        )
    if not variations(campaign):
        raise CommentSetupError(
            "A comment campaign needs at least one line to post."
        )


async def sync_slots(database, campaign: dict[str, Any]) -> int:
    """Give the campaign one queued slot per comment asked for.

    Idempotent: it adds what is missing and removes only slots that have
    not been used. A comment already posted is never taken back, so
    lowering the number afterwards trims the queue rather than rewriting
    history.

    Returns the number of slots added.
    """
    validate(campaign)
    campaign_id = int(campaign["id"])
    wanted = int(campaign.get("comment_count") or 0)
    url = (campaign.get("target_url") or "").strip()
    session = database.session

    existing = (await session.execute(
        text(
            "SELECT COUNT(*) FROM outreach_targets "
            " WHERE campaign_id = :cid AND username LIKE :prefix"
        ),
        {"cid": campaign_id, "prefix": f"{SLOT_PREFIX}%"},
    )).scalar_one()
    existing = int(existing or 0)

    # The video can be changed while the campaign is stopped; slots that
    # have not run yet should point at the new one rather than quietly
    # commenting on the old.
    await session.execute(
        text(
            f"""
            UPDATE outreach_targets
               SET profile_url = :url, updated_at = {UTC_NOW}
             WHERE campaign_id = :cid
               AND username LIKE :prefix
               AND status = :queued
               AND profile_url IS DISTINCT FROM :url
            """
        ),
        {"cid": campaign_id, "url": url, "prefix": f"{SLOT_PREFIX}%",
         "queued": TARGET_QUEUED},
    )

    added = 0
    if wanted > existing:
        rows = [
            {
                "cid": campaign_id,
                "username": slot_name(i),
                "url": url,
                "status": TARGET_QUEUED,
            }
            for i in range(existing + 1, wanted + 1)
        ]
        await session.execute(
            text(
                f"""
                INSERT INTO outreach_targets
                        (campaign_id, username, profile_url, status,
                         attempts, created_at, updated_at)
                VALUES (:cid, :username, :url, :status, 0,
                        {UTC_NOW}, {UTC_NOW})
                ON CONFLICT DO NOTHING
                """
            ),
            rows,
        )
        added = len(rows)
    elif wanted < existing:
        # Only ones that never ran. A slot that has commented stays.
        await session.execute(
            text(
                """
                DELETE FROM outreach_targets
                 WHERE campaign_id = :cid
                   AND username LIKE :prefix
                   AND status = :queued
                   AND id IN (
                         SELECT id FROM outreach_targets
                          WHERE campaign_id = :cid
                            AND username LIKE :prefix
                            AND status = :queued
                          ORDER BY id DESC
                          LIMIT :surplus
                       )
                """
            ),
            {"cid": campaign_id, "prefix": f"{SLOT_PREFIX}%",
             "queued": TARGET_QUEUED, "surplus": existing - wanted},
        )

    await session.commit()
    return added
