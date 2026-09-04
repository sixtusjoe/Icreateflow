"""Mock messenger — the driver that never opens a browser.

Two jobs:

1. Tests. Every queue / retry / account-pause path is exercised through
   this driver, so the suite runs with no browser and sends nothing.
2. Dry runs. Point `outreach_driver` at "mock" in the admin panel and a
   campaign executes end to end — jobs claimed, results recorded, dashboard
   updating — without contacting the platform. That is the intended way to
   rehearse a campaign before switching the driver over.

Outcomes are scripted rather than random by default, so a test asserting
"the third attempt fails" gets that every run.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional, Sequence

from services.outreach.browser import MessageResult
from services.outreach.constants import RESULT_UNKNOWN


class MockMessenger:
    """A driver whose results are decided by configuration, not a page.

    outcomes
        A sequence consumed one per call. An item may be a `MessageResult`,
        a `(status, error)` tuple meaning failure, or `None`/`"sent"` for
        success. Once exhausted, `default` is used.
    handler
        `handler(account, target, message) -> MessageResult | None` for
        tests that need to decide per call. Takes precedence over
        `outcomes`.
    delay_seconds
        Simulated send latency.
    """

    name = "mock"

    def __init__(
        self,
        outcomes: Optional[Sequence[Any]] = None,
        handler: Optional[Callable[..., Any]] = None,
        default: Any = "sent",
        delay_seconds: float = 0.0,
        **_ignored: Any,
    ):
        self._outcomes = list(outcomes or [])
        self._handler = handler
        self._default = default
        self._delay = delay_seconds
        self.started = False
        #: Every (account_id, username, message) this driver was asked to
        #: send — the assertion surface for tests.
        self.sent: list[tuple[Optional[int], str, str]] = []
        self.released: list[int] = []

    async def startup(self) -> None:
        self.started = True

    @staticmethod
    def _coerce(outcome: Any) -> MessageResult:
        if isinstance(outcome, MessageResult):
            return outcome
        if outcome is None or outcome == "sent":
            return MessageResult.sent(driver="mock")
        if isinstance(outcome, tuple):
            status, error = (list(outcome) + [None, None])[:2]
            return MessageResult.failure(status or RESULT_UNKNOWN, error or status, driver="mock")
        if isinstance(outcome, str):
            return MessageResult.failure(outcome, outcome, driver="mock")
        if isinstance(outcome, BaseException):
            raise outcome
        return MessageResult.failure(RESULT_UNKNOWN, f"Unrecognised mock outcome: {outcome!r}")

    async def send_message(
        self, account: dict[str, Any], target: dict[str, Any], message: str
    ) -> MessageResult:
        if self._delay:
            await asyncio.sleep(self._delay)
        self.sent.append((account.get("id"), target.get("username", ""), message))

        if self._handler is not None:
            outcome = self._handler(account, target, message)
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            return self._coerce(outcome)

        outcome = self._outcomes.pop(0) if self._outcomes else self._default
        return self._coerce(outcome)

    async def release_account(self, account_id: int) -> None:
        self.released.append(account_id)

    async def shutdown(self) -> None:
        self.started = False
