"""Letting a customer watch — and drive — the sign-in browser in the page.

The browser that signs an account in runs on the server. Someone has to see
it, and until now "someone" meant an operator with an SSH tunnel, a VNC
client and a shared password. No customer will ever do that, so the account
connect flow was effectively "paste a Playwright storage_state JSON", which
is worse.

This is the bridge: a short-lived ticket, handed only to the signed-in owner
of the account, that lets their page open a websocket the backend proxies to
the local VNC server. The VNC port itself stays bound to localhost and is
never exposed; the only way in is a ticket this module issued.

A ticket is single-use and short-lived on purpose. It travels in a URL —
websockets cannot carry an Authorization header from the browser — and a URL
ends up in history, logs and referrers. A leaked one must already be spent
and expired by the time it lands anywhere.
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

#: How long a ticket is good for. Long enough to open a socket, far too
#: short to be worth stealing out of a log.
TICKET_TTL_SECONDS = int(os.environ.get("ICREATE_VIEWER_TICKET_TTL", "60"))

#: Where the VNC server for the sign-in display listens. Localhost only —
#: this is the whole security model, and nothing here should ever bind it
#: anywhere else.
VNC_HOST = os.environ.get("ICREATE_VIEWER_VNC_HOST", "127.0.0.1")
VNC_PORT = int(os.environ.get("ICREATE_VIEWER_VNC_PORT", "5900"))


@dataclass(frozen=True)
class Ticket:
    value: str
    account_id: int
    user_id: Optional[int]
    expires_at: float

    def expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at


_TICKETS: dict[str, Ticket] = {}


def issue(account_id: int, user_id: Optional[int]) -> Ticket:
    """Mint a ticket for this user to watch this account's sign-in."""
    _sweep()
    ticket = Ticket(
        value=secrets.token_urlsafe(32),
        account_id=int(account_id),
        user_id=None if user_id is None else int(user_id),
        expires_at=time.time() + TICKET_TTL_SECONDS,
    )
    _TICKETS[ticket.value] = ticket
    return ticket


def redeem(value: str, account_id: int) -> Optional[Ticket]:
    """Spend a ticket, or return None if it cannot be spent.

    Single use: redeeming removes it whether or not it turns out to match,
    so a guessed-at or replayed value cannot be tried twice.
    """
    ticket = _TICKETS.pop((value or "").strip(), None)
    if ticket is None:
        return None
    if ticket.expired():
        return None
    if ticket.account_id != int(account_id):
        return None
    return ticket


def _sweep(now: Optional[float] = None) -> None:
    when = now if now is not None else time.time()
    for value in [v for v, t in _TICKETS.items() if t.expired(when)]:
        _TICKETS.pop(value, None)


def outstanding() -> int:
    """How many unspent, unexpired tickets exist. For tests and diagnostics."""
    _sweep()
    return len(_TICKETS)


def clear() -> None:
    _TICKETS.clear()
