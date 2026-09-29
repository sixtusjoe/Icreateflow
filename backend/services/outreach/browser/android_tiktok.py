"""TikTok follows through the real Android app, on a phone over adb.

Why this exists: TikTok web accepts a follow from these accounts, answers
`status_code: 0`, turns the button to "Following" — and discards it. Reload
and it says "Follow" again (measured 2026-09-23, three of three). The app
does not do that. Measured 2026-09-24 on account #28: one tap in the app,
and after the app was restarted the target's followers read 221 → 222 and
the account's Following 35 → 36.

So this driver follows and does nothing else. DMs, comments and discovery
stay on the browser; the runner only routes a *follow* here, and only for
an account that has a phone assigned.

It needs nothing installed on the phone: USB debugging, the TikTok app
signed in, and `adb` on this machine. Everything is three adb commands —
open a deep link, dump the screen's accessibility tree, tap a coordinate.
The screen is read from that tree, never from pixels.

The rules the browser driver learned the hard way hold here too:

* The button is not evidence. After the tap the profile is opened again
  from scratch and read again; only that counts.
* The profile's own control, never a suggestion's. TikTok puts a row of
  "Follow back" buttons for suggested accounts under the header. The
  profile's own button is the first one *below the stats row*.
* The right account, or nothing. A phone is a person's phone; it may be
  switched to somebody's own TikTok. Before following, the driver opens
  the handle the account is supposed to be and checks that the app shows
  it as *its own* profile. A mismatch pauses the account.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.outreach.browser import MessageResult
from services.outreach.constants import (
    RESULT_ALREADY_FOLLOWING,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_DEVICE_UNAVAILABLE,
    RESULT_FOLLOW_DISCARDED,
    RESULT_FOLLOW_LIMITED,
    RESULT_FOLLOW_REQUESTED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_NAVIGATION_TIMEOUT,
    RESULT_NOT_FOLLOWING,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_UNEXPECTED_PAGE,
    RESULT_UNKNOWN,
)

PACKAGE = "com.zhiliaoapp.musically"

#: FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_CLEAR_TASK. Every profile opens in
#: a fresh task, so each read is a real reload — and the app's back stack
#: does not grow by one profile per target over a run of hundreds.
_FRESH_TASK = "0x10008000"

#: How long a profile gets to render before we give up on it. Measured: a
#: profile is readable about four seconds after the deep link.
PROFILE_WAIT_S = float(os.environ.get("ICREATE_OUTREACH_DEVICE_PROFILE_WAIT", "20"))
#: How long the button gets to change after the tap.
CONFIRM_WAIT_S = 8.0
POLL_S = 1.0
#: How long a confirmed "this phone is signed in as X" is trusted. A person
#: can switch accounts at any moment, so not forever; checking before every
#: follow would double the time each one takes.
IDENTITY_TTL_S = 600.0
ADB_TIMEOUT_S = 30.0

DEBUG_DIR = os.environ.get("ICREATE_OUTREACH_DEBUG_DIR", "outreach-debug")

#: The profile's own control, by what it says. "Following " comes with a
#: trailing space (it carries a dropdown arrow), so labels are stripped.
_CAN_FOLLOW = ("follow", "follow back")
_FOLLOWING = ("following", "friends")
_PENDING = ("requested",)

#: Only things read off the real app, or the web driver's wording where the
#: app was not seen to differ. A phrase in `_MISSING` skips the target for
#: good, so nothing guessed belongs there.
_MISSING = ("couldn't find this account",)
_LOGIN_WALL = ("log in to tiktok", "sign up for tiktok", "log in or sign up")
_CHALLENGE = (
    "verify to continue",
    "drag the slider",
    "drag the puzzle",
    "select 2 objects",
    "verification failed",
)
_LIMITED = (
    "following too fast",
    "you are visiting too frequently",
    "too many attempts",
    "too many requests",
    "daily limit",
    "try again later",
)
#: What tapping Following/Friends opens: a bottom sheet (display name,
#: "Customise name", "Unfollow"), measured on the phone 2026-09-24. Exact
#: labels only — "cancel request" is the private-account equivalent and
#: was not seen, so it is matched but not relied on.
_UNFOLLOW_CHOICES = ("unfollow", "cancel request")

#: Only the signed-in account's own profile offers these.
_SELF_MARKERS = ("private videos", "create a story", "edit profile")

#: How far under the stats row the profile's button may sit. It is ~30px
#: below; the suggested-accounts row is ~650px below.
_BUTTON_BAND_PX = 400


# --- reading the screen --------------------------------------------------


@dataclass
class Node:
    text: str
    desc: str
    bounds: tuple[int, int, int, int]
    clickable: bool = False

    @property
    def label(self) -> str:
        return self.text.strip().lower()

    @property
    def top(self) -> int:
        return self.bounds[1]

    @property
    def bottom(self) -> int:
        return self.bounds[3]

    @property
    def centre(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2


_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_nodes(xml: str) -> list[Node]:
    """Every node in a `uiautomator dump`, flattened. [] for junk."""
    start = xml.find("<?xml")
    if start < 0:
        start = xml.find("<hierarchy")
    end = xml.rfind("</hierarchy>")
    if start < 0 or end < 0:
        return []
    try:
        root = ET.fromstring(xml[start:end + len("</hierarchy>")])
    except ET.ParseError:
        return []
    nodes = []
    for el in root.iter("node"):
        m = _BOUNDS.fullmatch(el.get("bounds") or "")
        if not m:
            continue
        nodes.append(Node(
            text=el.get("text") or "",
            desc=el.get("content-desc") or "",
            bounds=tuple(int(v) for v in m.groups()),  # type: ignore[arg-type]
            clickable=el.get("clickable") == "true",
        ))
    return nodes


@dataclass
class ProfileView:
    """What one screen of the app says about a profile."""

    handle: Optional[str] = None
    #: "can_follow" / "following" / "pending" / None (no control found).
    state: Optional[str] = None
    control: Optional[Node] = None
    followers: Optional[str] = None
    is_self: bool = False
    missing: bool = False
    login_wall: bool = False
    challenge: bool = False
    limit_notice: Optional[str] = None
    texts: list[str] = field(default_factory=list)


def _has(haystack: list[str], needles: tuple[str, ...]) -> Optional[str]:
    for text in haystack:
        low = text.lower()
        for needle in needles:
            if needle in low:
                return text
    return None


def read_profile(nodes: list[Node]) -> ProfileView:
    """Make sense of a profile screen.

    The own-button rule, measured on the live app: the stats row labels
    ("Following", "Followers", "Likes") come first, and the profile's own
    Follow/Following sits directly under them. Suggested accounts' "Follow
    back" buttons are further down. Note the stats *label* "Following" is
    above the anchor, so it can never be mistaken for the button.
    """
    view = ProfileView()
    texts = [n.text for n in nodes if n.text.strip()] + \
            [n.desc for n in nodes if n.desc.strip()]
    view.texts = texts

    handles = [n for n in nodes if re.fullmatch(r"@[\w.]{1,30}", n.text.strip())]
    if handles:
        view.handle = min(handles, key=lambda n: n.top).text.strip()[1:]

    view.missing = _has(texts, _MISSING) is not None
    view.login_wall = _has(texts, _LOGIN_WALL) is not None
    view.challenge = _has(texts, _CHALLENGE) is not None
    view.limit_notice = _has(texts, _LIMITED)
    view.is_self = any(
        (n.desc or n.text).strip().lower() in _SELF_MARKERS for n in nodes)

    anchor = [n for n in nodes if n.label == "followers"]
    if anchor:
        stats = min(anchor, key=lambda n: n.top)
        # The count sits over its label, in the same column.
        above = [n for n in nodes
                 if n.bottom <= stats.top + 8 and n.top >= stats.top - 120
                 and n.bounds[0] < stats.bounds[2] and n.bounds[2] > stats.bounds[0]
                 and re.fullmatch(r"[\d.,]+[KMB]?", n.text.strip())]
        if above:
            view.followers = max(above, key=lambda n: n.top).text.strip()

        floor = stats.bottom
        buttons = [n for n in nodes
                   if n.label in _CAN_FOLLOW + _FOLLOWING + _PENDING
                   and floor <= n.top <= floor + _BUTTON_BAND_PX]
        if buttons:
            own = min(buttons, key=lambda n: n.top)
            view.control = own
            if own.label in _FOLLOWING:
                view.state = "following"
            elif own.label in _PENDING:
                view.state = "pending"
            else:
                view.state = "can_follow"
    return view


def _same_handle(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return a.strip().lstrip("@").lower() == b.strip().lstrip("@").lower()


# --- talking to the phone ------------------------------------------------


def find_adb() -> Optional[str]:
    """The adb binary: an explicit setting, then PATH, then the SDK we set up."""
    configured = os.environ.get("ICREATE_OUTREACH_ADB")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("adb")
    if found:
        return found
    for candidate in (
        Path.home() / "android/sdk/platform-tools/adb",
        Path.home() / "Library/Android/sdk/platform-tools/adb",
    ):
        if candidate.exists():
            return str(candidate)
    return None


class AdbError(RuntimeError):
    pass


class Adb:
    """One phone. Tests replace this with a scripted fake."""

    def __init__(self, serial: str, binary: Optional[str] = None):
        self.serial = serial
        self.binary = binary or find_adb()

    async def run(self, *args: str, timeout: float = ADB_TIMEOUT_S) -> str:
        if not self.binary:
            raise AdbError("adb is not installed on this machine")
        proc = await asyncio.create_subprocess_exec(
            self.binary, "-s", self.serial, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise AdbError(f"adb {' '.join(args[:2])} timed out after {timeout:.0f}s")
        return out.decode("utf-8", "replace")

    async def shell(self, command: str) -> str:
        return await self.run("shell", command)

    async def state(self) -> str:
        """"device" when usable; "unauthorized", "offline" or "" otherwise."""
        try:
            return (await self.run("get-state", timeout=10)).strip().splitlines()[-1]
        except (AdbError, IndexError):
            return ""

    async def dump(self) -> str:
        # To a file and back: `dump /dev/tty` interleaves a status line with
        # the XML on some builds.
        return await self.run(
            "exec-out", "sh", "-c",
            "uiautomator dump /sdcard/icf_ui.xml >/dev/null 2>&1; "
            "cat /sdcard/icf_ui.xml; rm -f /sdcard/icf_ui.xml")

    async def open_profile(self, username: str) -> None:
        await self.shell(
            f"am start -f {_FRESH_TASK} -a android.intent.action.VIEW "
            f"-d https://www.tiktok.com/@{username} -p {PACKAGE}")

    async def tap(self, x: int, y: int) -> None:
        await self.shell(f"input tap {x} {y}")

    async def screenshot(self, path: str) -> bool:
        """Best effort. A flip phone has two displays; the first is the main one."""
        ids = re.findall(r"Display (\d+)", await self.shell(
            "dumpsys SurfaceFlinger --display-id"))
        flag = f"-d {ids[0]} " if ids else ""
        await self.shell(f"screencap {flag}-p /sdcard/icf_s.png")
        await self.run("pull", "/sdcard/icf_s.png", path)
        await self.shell("rm -f /sdcard/icf_s.png")
        return Path(path).exists()


# --- the driver ----------------------------------------------------------


class AndroidTikTokFollower:
    """Follows on TikTok by driving the app on an attached phone."""

    name = "android_tiktok"
    PLATFORM = "tiktok"

    def __init__(self, adb_factory: Any = None, **_ignored: Any):
        # `headless` / `on_disconnect` are browser concerns; accepted and
        # ignored so the runner can build every driver the same way.
        self._adb_factory = adb_factory or Adb
        self._locks: dict[str, asyncio.Lock] = {}
        #: serial → (handle, when it was confirmed)
        self._identity: dict[str, tuple[str, float]] = {}

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        self._identity.clear()

    async def release_account(self, account_id: int) -> None:
        # Something went wrong with this account: check who the phone is
        # signed in as again before the next follow.
        self._identity.clear()

    async def send_message(self, account, target, message) -> MessageResult:
        return MessageResult.failure(
            RESULT_UNEXPECTED_PAGE,
            "The phone driver only follows; messages go through the browser")

    async def comment_on_video(self, account, target) -> MessageResult:
        return MessageResult.failure(
            RESULT_UNEXPECTED_PAGE,
            "The phone driver only follows; comments go through the browser")

    # -- helpers ----------------------------------------------------------

    async def _look(self, adb) -> ProfileView:
        return read_profile(parse_nodes(await adb.dump()))

    async def _open_and_read(self, adb, username: str) -> ProfileView:
        """Open a profile fresh and wait until it is this profile, rendered."""
        await adb.open_profile(username)
        deadline = time.monotonic() + PROFILE_WAIT_S
        view = ProfileView()
        while True:
            view = await self._look(adb)
            if view.challenge or view.missing or view.login_wall:
                return view
            if _same_handle(view.handle, username) and (view.state or view.is_self):
                return view
            if time.monotonic() >= deadline:
                return view
            await asyncio.sleep(POLL_S)

    async def _ready(self, adb) -> Optional[str]:
        """Why this phone cannot be used right now, or None if it can."""
        state = await adb.state()
        if state == "unauthorized":
            return ("The phone is connected but has not allowed this computer "
                    "— unlock it and accept the USB debugging prompt")
        if state != "device":
            return "The phone is not connected — plug it in with USB debugging on"
        power = await adb.shell("dumpsys power")
        if "mWakefulness=Awake" not in power:
            await adb.shell("input keyevent KEYCODE_WAKEUP")
            await asyncio.sleep(1.0)
        window = await adb.shell("dumpsys window")
        if re.search(r"mDreamingLockscreen=true|isKeyguardShowing=true|"
                     r"mShowingLockscreen=true", window):
            return "The phone is locked — unlock it and leave the screen on"
        if PACKAGE not in await adb.shell(f"pm path {PACKAGE}"):
            return "TikTok is not installed on the phone"
        return None

    async def _confirm_identity(self, adb, handle: str) -> Optional[str]:
        """None if the app is signed in as `handle`, else what is wrong."""
        cached = self._identity.get(adb.serial)
        if cached and _same_handle(cached[0], handle) \
                and time.monotonic() - cached[1] < IDENTITY_TTL_S:
            return None
        view = await self._open_and_read(adb, handle.lstrip("@"))
        if view.login_wall:
            return "TikTok on the phone is signed out — sign in to @" + handle.lstrip("@")
        if view.challenge:
            return "TikTok on the phone is showing a verification puzzle"
        if not (_same_handle(view.handle, handle) and view.is_self):
            return (f"TikTok on the phone is not signed in as @{handle.lstrip('@')} "
                    f"— switch the app to that account")
        self._identity[adb.serial] = (handle, time.monotonic())
        return None

    async def _evidence(self, adb, username: str, reason: str) -> Optional[str]:
        if not DEBUG_DIR:
            return None
        try:
            directory = Path(DEBUG_DIR)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            path = str(directory / f"{stamp}-{username}-phone-{reason}.png")
            return path if await adb.screenshot(path) else None
        except Exception as exc:  # noqa: BLE001 — evidence is best effort
            print(f"[outreach] phone screenshot failed: {exc}", flush=True)
            return None

    # -- the one thing it does -------------------------------------------

    async def follow_target(self, account: dict[str, Any],
                            target: dict[str, Any]) -> MessageResult:
        serial = (account.get("device_serial") or "").strip()
        handle = (account.get("device_handle") or "").strip().lstrip("@")
        username = (target.get("username") or "").strip().lstrip("@")
        if not serial:
            return MessageResult.failure(
                RESULT_DEVICE_UNAVAILABLE, "No phone is assigned to this account")
        if not handle:
            return MessageResult.failure(
                RESULT_DEVICE_UNAVAILABLE,
                "Set the TikTok handle this account's phone is signed in as, "
                "so it cannot follow from the wrong account")
        lock = self._locks.setdefault(serial, asyncio.Lock())
        async with lock:
            try:
                return await self._follow(self._adb_factory(serial), handle, username)
            except AdbError as exc:
                return MessageResult.failure(
                    RESULT_DEVICE_UNAVAILABLE, f"Could not talk to the phone: {exc}")
            except Exception as exc:  # noqa: BLE001 — a driver fault is a job failure
                return MessageResult.failure(
                    RESULT_UNKNOWN, f"{type(exc).__name__}: {exc}"[:500])

    async def unfollow_target(self, account: dict[str, Any],
                              target: dict[str, Any]) -> MessageResult:
        """Unfollow one profile in the app. Never follows anyone.

        Only a Following/Friends/Requested control is ever tapped; that
        opens a bottom sheet, and "Unfollow" in the sheet is the action.
        A profile reading Follow is reported and left alone.
        """
        serial = (account.get("device_serial") or "").strip()
        handle = (account.get("device_handle") or "").strip().lstrip("@")
        username = (target.get("username") or "").strip().lstrip("@")
        if not serial:
            return MessageResult.failure(
                RESULT_DEVICE_UNAVAILABLE, "No phone is assigned to this account")
        if not handle:
            return MessageResult.failure(
                RESULT_DEVICE_UNAVAILABLE,
                "Set the TikTok handle this account's phone is signed in as, "
                "so it cannot unfollow from the wrong account")
        lock = self._locks.setdefault(serial, asyncio.Lock())
        async with lock:
            try:
                return await self._unfollow(self._adb_factory(serial), handle, username)
            except AdbError as exc:
                return MessageResult.failure(
                    RESULT_DEVICE_UNAVAILABLE, f"Could not talk to the phone: {exc}")
            except Exception as exc:  # noqa: BLE001
                return MessageResult.failure(
                    RESULT_UNKNOWN, f"{type(exc).__name__}: {exc}"[:500])

    async def _unfollow(self, adb, handle: str, username: str) -> MessageResult:
        problem = await self._ready(adb)
        if problem:
            return MessageResult.failure(RESULT_DEVICE_UNAVAILABLE, problem)
        problem = await self._confirm_identity(adb, handle)
        if problem:
            self._identity.pop(adb.serial, None)
            return MessageResult.failure(RESULT_DEVICE_UNAVAILABLE, problem)

        view = await self._open_and_read(adb, username)
        if view.challenge:
            return MessageResult.failure(
                RESULT_CHALLENGE_REQUIRED,
                "TikTok on the phone is showing a verification puzzle — "
                "solve it on the phone")
        if view.login_wall:
            self._identity.pop(adb.serial, None)
            return MessageResult.failure(
                RESULT_DEVICE_UNAVAILABLE,
                f"TikTok on the phone is signed out — sign in to @{handle}")
        if view.missing:
            return MessageResult.failure(RESULT_PROFILE_UNAVAILABLE, "Profile not found")
        if not _same_handle(view.handle, username):
            return MessageResult.failure(
                RESULT_NAVIGATION_TIMEOUT,
                f"@{username}'s profile did not load on the phone",
                screenshot=await self._evidence(adb, username, "no-profile"))
        if view.is_self:
            return MessageResult.failure(
                RESULT_MESSAGING_UNAVAILABLE, "That is this account's own profile")
        if view.state == "can_follow":
            return MessageResult.done(RESULT_NOT_FOLLOWING, via="phone")
        if view.state not in ("following", "pending") or view.control is None:
            return MessageResult.failure(
                RESULT_MESSAGING_UNAVAILABLE,
                f"No follow control on @{username}'s profile",
                screenshot=await self._evidence(adb, username, "no-button"))

        await adb.tap(*view.control.centre)
        choice = None
        deadline = time.monotonic() + CONFIRM_WAIT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_S)
            nodes = parse_nodes(await adb.dump())
            options = [n for n in nodes if n.label in _UNFOLLOW_CHOICES]
            if options:
                # The sheet rises from the bottom; its entry is the lowest.
                choice = max(options, key=lambda n: n.top)
                break
        if choice is None:
            await adb.shell("input keyevent KEYCODE_BACK")
            return MessageResult.failure(
                RESULT_UNEXPECTED_PAGE,
                f"Tapping Following on @{username} opened no Unfollow option",
                screenshot=await self._evidence(adb, username, "no-unfollow"))
        await adb.tap(*choice.centre)

        # Mutual follows ("Friends") get asked again, measured 2026-09-24 on
        # @depay038: a dialog "Unfollow this person? You and this person are
        # currently friends." with Cancel and Unfollow. Answered once — its
        # Unfollow is the exact label, and the only other choice is Cancel.
        after = None
        confirmed = False
        deadline = time.monotonic() + CONFIRM_WAIT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_S)
            nodes = parse_nodes(await adb.dump())
            after = read_profile(nodes)
            if after.challenge or after.state == "can_follow":
                break
            if not confirmed:
                again = [n for n in nodes if n.label == "unfollow"]
                if again and any(n.label == "cancel" for n in nodes):
                    await adb.tap(*again[0].centre)
                    confirmed = True
                    deadline = time.monotonic() + CONFIRM_WAIT_S
        if after is not None and after.challenge:
            return MessageResult.failure(
                RESULT_CHALLENGE_REQUIRED,
                "TikTok showed a verification puzzle after the tap")

        again = await self._open_and_read(adb, username)
        if _same_handle(again.handle, username) and again.state == "can_follow":
            return MessageResult.sent(
                via="phone", action="unfollow",
                followers_before=view.followers, followers_after=again.followers)
        if after is not None and after.state == "can_follow":
            return MessageResult.failure(
                RESULT_FOLLOW_DISCARDED,
                f"@{username} showed Follow after unfollowing, but Following "
                f"again after a reload — TikTok did not keep the unfollow",
                screenshot=await self._evidence(adb, username, "unfollow-discarded"))
        said = after.limit_notice if after is not None else None
        return MessageResult.failure(
            RESULT_FOLLOW_LIMITED,
            said or (f"@{username} is still followed after Unfollow was tapped "
                     f"— the account has most likely hit its limit"),
            platform_said=said,
            screenshot=await self._evidence(adb, username, "unfollow-unchanged"))

    async def _follow(self, adb, handle: str, username: str) -> MessageResult:
        problem = await self._ready(adb)
        if problem:
            return MessageResult.failure(RESULT_DEVICE_UNAVAILABLE, problem)
        problem = await self._confirm_identity(adb, handle)
        if problem:
            self._identity.pop(adb.serial, None)
            return MessageResult.failure(RESULT_DEVICE_UNAVAILABLE, problem)

        view = await self._open_and_read(adb, username)
        if view.challenge:
            return MessageResult.failure(
                RESULT_CHALLENGE_REQUIRED,
                "TikTok on the phone is showing a verification puzzle — "
                "solve it on the phone",
                screenshot=await self._evidence(adb, username, "challenge"))
        if view.login_wall:
            self._identity.pop(adb.serial, None)
            return MessageResult.failure(
                RESULT_DEVICE_UNAVAILABLE,
                f"TikTok on the phone is signed out — sign in to @{handle}")
        if view.missing:
            return MessageResult.failure(
                RESULT_PROFILE_UNAVAILABLE, "Profile not found")
        if not _same_handle(view.handle, username):
            top = (await adb.shell("dumpsys activity activities")).find(PACKAGE)
            if top < 0:
                return MessageResult.failure(
                    RESULT_DEVICE_UNAVAILABLE,
                    "TikTok did not come to the front — the phone may be locked")
            return MessageResult.failure(
                RESULT_NAVIGATION_TIMEOUT,
                f"@{username}'s profile did not load on the phone",
                screenshot=await self._evidence(adb, username, "no-profile"))
        if view.is_self:
            return MessageResult.failure(
                RESULT_MESSAGING_UNAVAILABLE, "That is this account's own profile")
        if view.state == "following":
            return MessageResult.done(RESULT_ALREADY_FOLLOWING, via="phone")
        if view.state == "pending":
            return MessageResult.done(RESULT_FOLLOW_REQUESTED, via="phone")
        if view.state != "can_follow" or view.control is None:
            return MessageResult.failure(
                RESULT_MESSAGING_UNAVAILABLE,
                f"No follow button on @{username}'s profile",
                screenshot=await self._evidence(adb, username, "no-button"))

        before = view.followers
        await adb.tap(*view.control.centre)

        after = None
        deadline = time.monotonic() + CONFIRM_WAIT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_S)
            after = await self._look(adb)
            if after.challenge or after.state in ("following", "pending"):
                break
        if after is not None and after.challenge:
            return MessageResult.failure(
                RESULT_CHALLENGE_REQUIRED,
                "TikTok showed a verification puzzle after the tap",
                screenshot=await self._evidence(adb, username, "challenge"))
        if after is not None and after.state == "pending":
            return MessageResult.done(RESULT_FOLLOW_REQUESTED, via="phone")
        if after is None or after.state != "following":
            said = after.limit_notice if after is not None else None
            return MessageResult.failure(
                RESULT_FOLLOW_LIMITED,
                said or (f"The Follow button on @{username} did not change after "
                         f"being tapped on the phone — the account has most "
                         f"likely hit its follow limit"),
                platform_said=said,
                screenshot=await self._evidence(adb, username, "unchanged"))

        # The button says so. Open the profile again from scratch and read
        # it again: that, not the button, is the evidence.
        again = await self._open_and_read(adb, username)
        if _same_handle(again.handle, username) and again.state == "can_follow":
            return MessageResult.failure(
                RESULT_FOLLOW_DISCARDED,
                f"@{username} showed Following after the tap but Follow again "
                f"after a reload — TikTok did not keep the follow",
                screenshot=await self._evidence(adb, username, "discarded"))
        return MessageResult.sent(
            via="phone", followers_before=before, followers_after=again.followers)


async def connected_phones() -> dict[str, Any]:
    """Phones this machine can see, for the account page to offer.

    `{"adb": bool, "phones": [{"serial", "model", "state"}]}`. Never raises:
    a machine without adb simply has no phones.
    """
    binary = find_adb()
    if not binary:
        return {"adb": False, "phones": []}
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "devices", "-l",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
    except Exception:  # noqa: BLE001
        return {"adb": True, "phones": []}
    phones = []
    for line in out.decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        # Emulators are not phones worth assigning: they are what TikTok is
        # likeliest to treat the way it treats the web.
        if serial.startswith("emulator-"):
            continue
        model = next((p.split(":", 1)[1].replace("_", " ")
                      for p in parts[2:] if p.startswith("model:")), "")
        phones.append({"serial": serial, "model": model, "state": state})
    return {"adb": True, "phones": phones}
