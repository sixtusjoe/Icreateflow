"""Browser automation layer — the only part of outreach that knows what a
web page is.

Everything above this package (queue, account manager, result processor,
API, dashboard) deals in `MessageResult` and never imports Playwright. To
swap the automation technology, add a module here that implements
`MessengerDriver` and register it in `DRIVERS`; nothing else changes.

The contract:

    driver = get_driver("playwright_tiktok")
    await driver.startup()
    result = await driver.send_message(account, target, message)
    await driver.shutdown()

`account` is a plain dict with at least `id`, `name`, `platform` and
`session_state` (the decrypted Playwright storage-state JSON, or None).
`target` is a plain dict with `username` and `profile_url`. Neither is an
ORM object — the driver must not be able to touch the database.

A driver never raises for an expected failure: profile gone, DMs closed,
session expired, timeout and unexpected markup all come back as a
`MessageResult` with `success=False` and a status from
`services.outreach.constants`. Only a programming error should propagate.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from services.outreach.constants import (
    RESULT_SENT,
    RESULT_UNKNOWN,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MessageResult:
    """The structured outcome of one send attempt.

    Serializes to exactly the shape the spec calls for::

        {"success": true, "status": "sent", "error": null,
         "timestamp": "2026-09-04T12:00:00+00:00"}
    """

    success: bool
    status: str
    error: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    #: Free-form driver diagnostics (page URL, selector that missed, …).
    #: Logged, never shown as the user-facing error.
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def sent(cls, **detail: Any) -> "MessageResult":
        return cls(success=True, status=RESULT_SENT, detail=detail)

    @classmethod
    def failure(cls, status: str, error: str, **detail: Any) -> "MessageResult":
        return cls(success=False, status=status or RESULT_UNKNOWN, error=error, detail=detail)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class MessengerDriver(Protocol):
    """What every automation backend must provide."""

    name: str

    async def startup(self) -> None:
        """Acquire whatever the driver needs (launch a browser, …)."""

    async def send_message(
        self, account: dict[str, Any], target: dict[str, Any], message: str
    ) -> MessageResult:
        """Deliver `message` to `target` as `account`."""

    async def release_account(self, account_id: int) -> None:
        """Drop the per-account context after a job.

        Must NOT invalidate the stored session — the next job for this
        account has to be able to reuse it.
        """

    async def shutdown(self) -> None:
        """Release everything. Called once when the worker exits."""


#: name → "module:attribute". Imported lazily so a deployment that only
#: uses the mock driver never needs Playwright installed.
DRIVERS: dict[str, str] = {
    "mock": "services.outreach.browser.mock:MockMessenger",
    "playwright_tiktok": "services.outreach.browser.playwright_tiktok:PlaywrightTikTokMessenger",
}


class DriverUnavailable(RuntimeError):
    """The requested driver isn't registered, or its dependencies are missing."""


def get_driver(name: str, **kwargs: Any) -> MessengerDriver:
    """Instantiate a driver by registry name."""
    path = DRIVERS.get((name or "").strip())
    if not path:
        raise DriverUnavailable(
            f"Unknown outreach driver {name!r}. Available: {', '.join(sorted(DRIVERS))}"
        )
    module_name, _, attr = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise DriverUnavailable(
            f"Driver {name!r} is registered but its dependencies are not installed: {exc}"
        ) from exc
    return getattr(module, attr)(**kwargs)
