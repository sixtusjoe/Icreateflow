"""The vocabulary above the reader layer — and nothing else.

Deliberately thin. This module is the one thing every platform folder under
`net/` may share, so anything that creeps in here becomes something all
three platforms have to agree on. `playwright_base.py` is 3,689 lines for
exactly that reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class LeadRow:
    """One person a read found. Platform-agnostic on purpose."""

    username: str
    profile_url: str
    display_name: Optional[str] = None
    #: Where this lead came from — a post URL, a profile, a follower list.
    source: Optional[str] = None
    #: The platform's own id, when it gives one. Handles get changed;
    #: numeric ids do not, and a re-read that matches on the handle alone
    #: counts a renamed account as somebody new.
    platform_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "profile_url": self.profile_url,
            "display_name": self.display_name,
            "source": self.source,
            "platform_id": self.platform_id,
        }


@dataclass
class ReadResult:
    """The outcome of one read, with the rows it managed to collect.

    `ok` and `rows` are independent on purpose. A read that paged happily
    for twenty minutes and then hit an expired signature has both a real
    failure *and* real rows, and throwing either away is a bug: discarding
    the rows wastes twenty minutes of an account's daily budget, and
    discarding the failure is how a partial read gets reported as a
    complete one.
    """

    ok: bool
    #: A status from `services.outreach.constants` — never free text. The
    #: rule is already written into that module and applies here unchanged.
    status: str
    rows: list[LeadRow] = field(default_factory=list)
    error: Optional[str] = None
    #: Diagnostics: pages read, cursor reached, how many signatures it took.
    #: Logged, never shown as the user-facing error.
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Did the read reach the end of the list, rather than stopping?

        The distinction the whole layer exists to preserve. `ok` means
        nothing went wrong *so far*; this means there is nothing left.
        """
        return bool(self.ok and self.detail.get("exhausted"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "error": self.error,
            "rows": len(self.rows),
            "complete": self.complete,
            **{k: v for k, v in self.detail.items()},
        }
