"""A private screen per browser session.

Every visible browser used to draw on one shared display, `:99`, and x11vnc
streams a *display*, not a window. So anyone holding a viewer ticket saw
everything on it — including, with two people connecting accounts at the
same time, each other's login and each other's typing. Fine with one
operator, a credential leak between tenants the moment there are two.

So a session takes a display of its own: an Xvfb for it to draw on and an
x11vnc bound to loopback for the page to read, both torn down when the
session ends. The ticket carries the port, so a viewer can only ever reach
the screen it was issued for.

Where there is no Xvfb — a developer's Mac — `acquire` returns None and the
caller opens an ordinary window, which is what it did before.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
from dataclasses import dataclass
from typing import Optional

#: Display numbers to hand out. Above :99 so it cannot collide with the
#: shared one this replaces, or with anything a person started by hand.
FIRST_DISPLAY = int(os.environ.get("ICREATE_DISPLAY_FIRST", "101"))
LAST_DISPLAY = int(os.environ.get("ICREATE_DISPLAY_LAST", "140"))

GEOMETRY = os.environ.get("ICREATE_DISPLAY_GEOMETRY", "1280x800x24")

#: Same password file the shared server used. Every display can share it:
#: the password stops another local process connecting, and which *screen*
#: a viewer reaches is decided by the port in its ticket, not by the
#: password.
PASSWORD_FILE = os.environ.get(
    "ICREATE_VIEWER_VNC_PASSWORD_FILE", "/etc/icreateflow/vncpw.plain")


@dataclass
class Display:
    number: int
    vnc_port: int
    xvfb: asyncio.subprocess.Process
    x11vnc: asyncio.subprocess.Process

    @property
    def name(self) -> str:
        return f":{self.number}"

    @property
    def env(self) -> dict[str, str]:
        """What to hand a browser so it draws here."""
        return {"DISPLAY": self.name}


_TAKEN: set[int] = set()
_LOCK = asyncio.Lock()


def available() -> bool:
    """Can this host give a session its own screen?"""
    return bool(shutil.which("Xvfb") and shutil.which("x11vnc"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def acquire() -> Optional[Display]:
    """A display of one's own, or None where that is not possible."""
    if not available():
        return None
    async with _LOCK:
        number = next(
            (n for n in range(FIRST_DISPLAY, LAST_DISPLAY + 1)
             if n not in _TAKEN and not os.path.exists(f"/tmp/.X11-unix/X{n}")),
            None,
        )
        if number is None:
            return None
        _TAKEN.add(number)

    port = _free_port()
    try:
        xvfb = await asyncio.create_subprocess_exec(
            "Xvfb", f":{number}", "-screen", "0", GEOMETRY, "-nolisten", "tcp",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        # Give the server a moment to create its socket, or x11vnc races it.
        for _ in range(40):
            await asyncio.sleep(0.1)
            if os.path.exists(f"/tmp/.X11-unix/X{number}"):
                break
        args = ["x11vnc", "-display", f":{number}", "-rfbport", str(port),
                # Loopback only. The websocket relay is the sole way in, and
                # it demands a ticket first.
                "-localhost", "-forever", "-shared", "-quiet",
                "-defer", "5", "-wait", "5", "-nodpms", "-noxrecord",
                "-noxfixes"]
        if os.path.exists(PASSWORD_FILE):
            args += ["-passwdfile", PASSWORD_FILE]
        else:
            # Nothing to authenticate with. Still loopback-only, still behind
            # a ticket, but say so rather than pretend otherwise.
            args += ["-nopw"]
            print(f"[display] no {PASSWORD_FILE}; :{number} has no VNC "
                  f"password", flush=True)
        x11vnc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        async with _LOCK:
            _TAKEN.discard(number)
        print(f"[display] could not start :{number}: {exc}", flush=True)
        return None

    await asyncio.sleep(0.4)
    return Display(number=number, vnc_port=port, xvfb=xvfb, x11vnc=x11vnc)


async def release(display: Optional[Display]) -> None:
    """Give the screen back. Safe to call twice, and with None."""
    if display is None:
        return
    for proc in (display.x11vnc, display.xvfb):
        try:
            if proc.returncode is None:
                proc.terminate()
        except ProcessLookupError:
            pass
    for proc in (display.x11vnc, display.xvfb):
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    async with _LOCK:
        _TAKEN.discard(display.number)


def in_use() -> int:
    return len(_TAKEN)
