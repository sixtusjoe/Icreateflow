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

from services.outreach import vnc_auth

#: How long a ticket is good for. Long enough to open a socket, far too
#: short to be worth stealing out of a log.
TICKET_TTL_SECONDS = int(os.environ.get("ICREATE_VIEWER_TICKET_TTL", "60"))

#: Where the VNC server for the sign-in display listens. Localhost only —
#: this is the whole security model, and nothing here should ever bind it
#: anywhere else.
VNC_HOST = os.environ.get("ICREATE_VIEWER_VNC_HOST", "127.0.0.1")
VNC_PORT = int(os.environ.get("ICREATE_VIEWER_VNC_PORT", "5900"))

#: Where x11vnc's password lives. Read here and never sent anywhere: the
#: backend answers the password step itself, so the page is handed a stream
#: already past it. Shipping the password to the browser would work too, and
#: would mean every viewer had the key to a VNC port that is driving a real
#: browser with someone's account in it.
VNC_PASSWORD_FILE = os.environ.get(
    "ICREATE_VIEWER_VNC_PASSWORD_FILE", "/etc/icreateflow/vncpw.plain")


def vnc_password() -> str:
    """The VNC password, or "" if the server runs without one."""
    try:
        with open(VNC_PASSWORD_FILE, "r", encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


async def negotiate(reader, writer, send, receive) -> Optional[str]:
    """Complete the RFB handshake on the page's behalf.

    Returns None on success, or a reason to close on failure.

    The version exchange is passed through untouched. The security step is
    not: we authenticate to the VNC server with the password, and separately
    tell the page that this connection needs no security. From `ClientInit`
    onwards it is a plain byte relay again.
    """
    server_version = await reader.readexactly(12)
    await send(server_version)
    client_version = await receive()
    writer.write(client_version[:12])
    await writer.drain()

    count = (await reader.readexactly(1))[0]
    if count == 0:
        reason = await reader.readexactly(4)
        length = int.from_bytes(reason, "big")
        return (await reader.readexactly(length)).decode("utf-8", "replace")
    offered = await reader.readexactly(count)

    if 1 in offered:                      # None: nothing to answer
        writer.write(bytes([1]))
    elif 2 in offered:                    # VNC password
        writer.write(bytes([2]))
        await writer.drain()
        challenge = await reader.readexactly(16)
        writer.write(vnc_auth.challenge_response(vnc_password(), challenge))
    else:
        return f"VNC offered no security type we can answer: {list(offered)}"
    await writer.drain()

    result = int.from_bytes(await reader.readexactly(4), "big")
    if result != 0:
        return "the VNC password was refused"

    # As far as the page is concerned there was never a password.
    await send(bytes([1, 1]))             # one type on offer: None
    await receive()                       # its choice, which can only be None
    await send((0).to_bytes(4, "big"))    # and it succeeded
    return None


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
