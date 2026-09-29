"""Admin-configurable outreach controls.

Everything the operator can tune lives in `site_config` (the same table the
Clipping view-poll cadence uses) so it is editable from /admin without a
deploy. Per-campaign overrides live on the campaign row and win when set.

Reads are per-call — a value changed in the admin panel takes effect on the
worker's next tick, no restart.
"""
from __future__ import annotations

from typing import Any, Optional

import database as db

#: key -> (default, min, max). Bounds are clamps, not validation errors:
#: a nonsense value in site_config must never wedge the pipeline.
SPEC: dict[str, tuple[int, int, int]] = {
    # Ceiling on how many jobs one campaign start will enqueue.
    "outreach_max_jobs_per_campaign": (1000, 1, 100_000),
    # Ceiling on live+completed jobs handed to a single account per campaign.
    "outreach_max_jobs_per_account": (100, 1, 10_000),
    # How many times a retryable failure is re-queued before the target fails.
    "outreach_retry_limit": (3, 0, 20),
    # Jobs processed concurrently inside one worker process.
    "outreach_worker_concurrency": (2, 1, 20),
    # Consecutive account-fault failures before the account auto-pauses.
    "outreach_account_error_threshold": (5, 1, 100),
    # How long a claimed job stays claimed before the reaper requeues it.
    "outreach_job_lease_seconds": (600, 60, 7200),
    # Base delay before a retried job becomes claimable again (×attempt).
    "outreach_retry_backoff_seconds": (300, 5, 86_400),
    # Minimum gap between two sends from the same account.
    "outreach_min_send_interval_seconds": (15, 0, 3600),
    # Follow the target, wait, then message on a later pass. 0 disables it.
    "outreach_follow_wait_seconds": (0, 0, 86400),
    # Follow a profile that shows no Message button, then look again. Some
    # accounts accept messages only from people they follow, and the button
    # is genuinely absent until then. Following is a public action on the
    # sending account, so this is worth being able to turn off — set to 0.
    "outreach_follow_to_unlock": (1, 0, 1),
    # Sending accounts the local Mac worker drives at once, each in its own
    # visible Chromium window. One account per slot — leases are exclusive,
    # so a second slot takes the next free account rather than doubling up
    # on one, and every account keeps its own send interval. More slots than
    # you have accounts is harmless: the extras idle.
    "outreach_local_worker_concurrency": (2, 1, 8),
    # Seconds a worker sleeps when it finds no claimable job.
    "outreach_worker_idle_seconds": (10, 1, 300),
    # How long a campaign stands down after the platform says it has hit a
    # limit — one per activity, because they are not the same limit and do
    # not recover together. An account blocked from following can usually
    # still send, and the platform tracks them separately.
    #
    # These are the countdown the campaign page shows. **The defaults are
    # placeholders**: six hours is a guess chosen to err long, because
    # resuming too early re-triggers the block and a re-trigger is worse
    # than the wait. Measure how long a real block actually lasts and set
    # these to that, which is the whole point of having them here.
    # Actions one sending account may take in a rolling 24 hours — follows,
    # messages, comments, all of it together, because the platform counts
    # them against the same account and does not care which it was.
    #
    # This is the *proactive* half of limit handling. The reactive half
    # already exists: `follow_limited` and `rate_limited` are account faults
    # and pause the account once its error budget is spent. But by then the
    # platform has already told us, several times, which is exactly the
    # signal that costs accounts. A cap we enforce ourselves stops before
    # that conversation starts.
    #
    # Counted from the jobs themselves, not a counter, so a crash cannot
    # lose the count and let a restart exceed the cap. Profiles that turned
    # out to be followed already do not count — nothing was pressed.
    # Run browsers with no window on screen. 1 = headless, 0 = visible.
    #
    # Visible is what the local sender was built for: a verification puzzle
    # has to be solved by a person, and a drag-slider needs a real window.
    # But on a machine someone is working at, a window opening for every
    # job is its own problem, so this is a switch rather than a constant.
    #
    # The cost of turning it on is specific and worth knowing: nobody can
    # answer a challenge, so a job that hits one fails instead of waiting.
    # X is unaffected either way — its discovery needs a headed browser to
    # get a timeline at all, and says so with HEADED_DISCOVERY.
    "outreach_headless": (1, 0, 1),
    # --- Lead discovery ---
    # Profiles a discovery account may open in a rolling 24 hours. Harvesting
    # is a lot of page loads in a short window and is the likeliest way to
    # lose an account, so it is capped and the cap is meant to be tuned down
    # rather than up if a platform starts pushing back.
    # Seconds between profile visits during a search. Discovery is not
    # urgent, and going slowly is most of what keeps it unremarkable.
    "outreach_discovery_interval_seconds": (6, 1, 600),
    # Profiles one search may open, whatever the operator asked for.
    "outreach_discovery_max_per_search": (300, 1, 5_000),
    # How many times to scroll a comment list or likes dialog before moving
    # on. Both are paged: without this only the dozen that render first are
    # ever seen. More rounds means more people per post and more time on it.
    "outreach_discovery_scroll_rounds": (4, 0, 30),
}

#: Non-numeric settings.
DRIVER_KEY = "outreach_driver"
DRIVER_DEFAULT = "mock"
#: Not a driver: "let each job's platform choose". The only other value
#: that changes behaviour is `mock`; naming a single browser driver here is
#: a debugging pin, not a routing instruction.
DRIVER_AUTO = "auto"
WORKERS_ENABLED_KEY = "outreach_workers_enabled"

#: Hard ceiling on sending accounts, per the product spec. Not tunable —
#: raising it is a deliberate code change, not an admin toggle.
MAX_SENDING_ACCOUNTS = 20


def _coerce_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


async def get_all(database) -> dict[str, Any]:
    """Every outreach setting, resolved against defaults."""
    try:
        cfg = await db.get_site_config(database)
    except Exception:  # noqa: BLE001 — a config read must never break a send
        cfg = {}
    out: dict[str, Any] = {
        key: _coerce_int(cfg.get(key), default, lo, hi)
        for key, (default, lo, hi) in SPEC.items()
    }
    out[DRIVER_KEY] = (cfg.get(DRIVER_KEY) or DRIVER_DEFAULT).strip() or DRIVER_DEFAULT
    out[WORKERS_ENABLED_KEY] = str(cfg.get(WORKERS_ENABLED_KEY, "1")).strip().lower() not in (
        "0", "false", "no", "off",
    )
    return out


async def get_int(database, key: str) -> int:
    default, lo, hi = SPEC[key]
    try:
        cfg = await db.get_site_config(database)
    except Exception:  # noqa: BLE001
        return default
    return _coerce_int(cfg.get(key), default, lo, hi)


async def workers_enabled(database) -> bool:
    """The global kill switch behind the admin "Stop all workers" control."""
    try:
        cfg = await db.get_site_config(database)
    except Exception:  # noqa: BLE001
        return True
    return str(cfg.get(WORKERS_ENABLED_KEY, "1")).strip().lower() not in (
        "0", "false", "no", "off",
    )


async def driver_name(database, override: Optional[str] = None) -> str:
    if override:
        return override
    try:
        cfg = await db.get_site_config(database)
    except Exception:  # noqa: BLE001
        return DRIVER_DEFAULT
    return (cfg.get(DRIVER_KEY) or DRIVER_DEFAULT).strip() or DRIVER_DEFAULT


def campaign_limit(campaign: dict, settings: dict[str, Any], field: str, key: str) -> int:
    """Per-campaign override, falling back to the global setting.

    `field` is the campaign column, `key` the site_config key.
    """
    raw = campaign.get(field)
    if raw is None:
        return int(settings[key])
    default, lo, hi = SPEC[key]
    return _coerce_int(raw, default, lo, hi)


#: How long a campaign stands down after a platform limit, by activity.
#:
#: Deliberately not a setting. There is one limit timer in this system and
#: it is the countdown on the campaign page. A dial on the admin page read
#: as a second, competing timer — and the honest default is unknown anyway:
#: no platform tells us how long it will refuse us, so six hours is a guess
#: that only measurement should replace, in this file, with a note.
LIMIT_COOLDOWN_SECONDS: dict[str, int] = {
    "follow": 21_600,
    "message": 21_600,
    "comment": 21_600,
    "unfollow": 21_600,
}

#: What an unrecognised activity waits.
DEFAULT_LIMIT_COOLDOWN_SECONDS = 21_600


def limit_cooldown_seconds(
    activity: Optional[str], settings: Optional[dict[str, Any]] = None
) -> int:
    """How long a campaign doing `activity` waits out a platform limit.

    `settings` is accepted and ignored so callers need not know this
    stopped being configurable.
    """
    return LIMIT_COOLDOWN_SECONDS.get(
        (activity or "message"), DEFAULT_LIMIT_COOLDOWN_SECONDS)
