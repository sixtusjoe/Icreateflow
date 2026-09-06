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
    "outreach_min_send_interval_seconds": (45, 0, 3600),
    # Follow the target, wait, then message on a later pass. 0 disables it.
    "outreach_follow_wait_seconds": (0, 0, 86400),
    # Seconds a worker sleeps when it finds no claimable job.
    "outreach_worker_idle_seconds": (10, 1, 300),
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
