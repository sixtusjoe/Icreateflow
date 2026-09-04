"""Campaign counter maintenance.

The counters on `outreach_campaigns` are a cache for the dashboard; the
`outreach_targets` rows are the truth. Everything here recomputes from the
targets rather than incrementing, so a crashed worker, a manual DB fix, or
a double-processed job can never leave the numbers permanently wrong.
"""
from __future__ import annotations

from typing import Any

import database as db
from services.outreach.constants import (
    CAMPAIGN_COMPLETED,
    CAMPAIGN_RUNNING,
    TARGET_FAILED,
    TARGET_PROCESSING,
    TARGET_QUEUED,
    TARGET_SENT,
    TARGET_SKIPPED,
)


def totals_from_counts(counts: dict[str, int]) -> dict[str, int]:
    """Map a target status histogram to the campaign's counter columns."""
    successful = counts.get(TARGET_SENT, 0)
    failed = counts.get(TARGET_FAILED, 0)
    skipped = counts.get(TARGET_SKIPPED, 0)
    return {
        "total_targets": sum(counts.values()),
        "queued_count": counts.get(TARGET_QUEUED, 0) + counts.get(TARGET_PROCESSING, 0),
        "successful_count": successful,
        "failed_count": failed,
        "processed_count": successful + failed + skipped,
    }


async def refresh_campaign_totals(database, campaign_id: int) -> dict[str, int]:
    """Recompute and persist the counters for one campaign."""
    counts = await db.count_outreach_targets(database, campaign_id)
    totals = totals_from_counts(counts)
    await db.update_outreach_campaign(database, campaign_id, **totals)
    return totals


async def refresh_and_maybe_complete(database, campaign_id: int) -> dict[str, Any]:
    """Refresh counters and finish the campaign when nothing is left.

    A running campaign with no queued or processing target has done all the
    work it was given; flipping it to `completed` is what stops workers
    from picking it up and what the dashboard shows as 100%.
    """
    counts = await db.count_outreach_targets(database, campaign_id)
    totals = totals_from_counts(counts)
    campaign = await db.get_outreach_campaign(database, campaign_id)
    status = dict(campaign or {}).get("status")

    outstanding = counts.get(TARGET_QUEUED, 0) + counts.get(TARGET_PROCESSING, 0)
    updates: dict[str, Any] = dict(totals)
    if status == CAMPAIGN_RUNNING and outstanding == 0 and totals["total_targets"] > 0:
        updates["status"] = CAMPAIGN_COMPLETED
    await db.update_outreach_campaign(database, campaign_id, **updates)
    return updates
