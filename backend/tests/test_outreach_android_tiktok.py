"""TikTok follows through the app on a phone.

The screens below are cut down from real `uiautomator dump`s of the TikTok
app, 2026-09-24 — same texts, same coordinates. Two of their traps are
kept on purpose:

* The stats row has a label that says "Following". It sits above the
  profile's button, and must never be read as the button.
* Under the header is a row of suggested accounts with "Follow back"
  buttons. Tapping one follows a stranger and reports it as the target.

The fake phone remembers follows the way TikTok does — or, for `phantom`,
flips the button and forgets, which is what TikTok *web* does and the
reason this driver exists.
"""
from __future__ import annotations

from typing import Optional
from xml.sax.saxutils import quoteattr

import pytest

from services.outreach.browser import android_tiktok
from services.outreach.browser.android_tiktok import (
    AndroidTikTokFollower,
    parse_nodes,
    read_profile,
)
from services.outreach.constants import (
    IMMEDIATE_ACCOUNT_PAUSE_RESULTS,
    RESULT_ALREADY_FOLLOWING,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_DEVICE_UNAVAILABLE,
    RESULT_FOLLOW_DISCARDED,
    RESULT_FOLLOW_LIMITED,
    RESULT_NOT_FOLLOWING,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_SENT,
)


ME = "_lancastarmoon"


def _xml(nodes: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f"<node text={quoteattr(t)} content-desc={quoteattr(d)} "
        f'clickable="false" bounds="{b}" />'
        for t, d, b in nodes)
    return ("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
            f'<hierarchy rotation="0">{body}</hierarchy>')


def other_profile(handle: str, followed: bool, followers: int) -> str:
    """Someone else's profile, in the two layouts the app used."""
    if not followed:
        return _xml([
            ("S.H.A.N.N.Y", "", "[413,425][667,483]"),
            (f"@{handle}", "", "[356,483][724,522]"),
            ("249", "", "[144,549][407,607]"),
            ("Following", "", "[144,602][407,644]"),       # a label, not a button
            (str(followers), "", "[501,549][579,607]"),
            ("Followers", "", "[462,607][618,644]"),
            ("Likes", "", "[672,602][935,644]"),
            ("Follow", "", "[167,670][472,786]"),           # THE button
            ("Message", "", "[482,670][787,786]"),
            # Suggested accounts — must never be tapped.
            ("Follow back", "", "[73,1309][399,1393]"),
            ("Follow back", "", "[473,1309][799,1393]"),
        ])
    return _xml([
        ("S.H.A.N.N.Y", "", "[347,240][796,340]"),
        (f"@{handle}", "", "[347,345][699,384]"),
        ("249", "", "[347,410][495,468]"),
        ("Following", "", "[347,465][495,504]"),
        (str(followers), "", "[558,410][643,465]"),
        ("Followers", "", "[558,465][704,504]"),
        ("Message", "", "[226,546][400,651]"),
        ("Following ", "", "[648,546][870,651]"),           # trailing space is real
        ("", "Add person", "[933,546][1038,651]"),
    ])


def own_profile(handle: str) -> str:
    return _xml([
        ("Lancaster moon", "", "[347,231][1038,331]"),
        (f"@{handle}", "", "[347,336][626,375]"),
        ("36", "", "[347,412][495,470]"),
        ("Following", "", "[347,467][495,506]"),
        ("1,144", "", "[558,412][665,467]"),
        ("Followers", "", "[558,467][704,506]"),
        ("", "Create a Story", "[196,406][329,525]"),
        ("", "Private videos", "[374,664][540,769]"),
    ])


FOLLOW_BUTTON = (319, 728)
#: "Following " in the followed layout, and the sheet's "Unfollow" — both
#: from the dumps taken on the phone.
FOLLOWING_BUTTON = (759, 598)
UNFOLLOW_ENTRY = (474, 2418)
#: The second question friends get: "Unfollow this person? You and this
#: person are currently friends." Cancel | Unfollow.
FRIENDS_CONFIRM = (723, 1492)


class FakePhone:
    """A phone with TikTok on it, signed in as `signed_in`."""

    def __init__(self, serial: str = "PHONE1", *, signed_in: str = ME,
                 phantom: bool = False, ignore_taps: bool = False,
                 state: str = "device", locked: bool = False,
                 overlay: Optional[str] = None, keeps_unfollow: bool = True,
                 friends: bool = False):
        self.serial = serial
        self.signed_in = signed_in
        self.phantom = phantom
        self.ignore_taps = ignore_taps
        self._state = state
        self.locked = locked
        self.overlay = overlay
        self.keeps_unfollow = keeps_unfollow
        self.sheet = False
        self.friends = friends
        self.asking = False
        self.hidden: set[str] = set()   # showed Follow, server still following
        self.followed: set[str] = set()
        self.flipped: set[str] = set()   # button shows Following, server does not know
        self.current: Optional[str] = None
        self.followers = {"brownthickbeautiful": 221, "already": 50}
        self.taps: list[tuple[int, int]] = []
        self.opened: list[str] = []

    # --- the Adb surface the driver uses ---

    async def state(self) -> str:
        return self._state

    async def shell(self, command: str) -> str:
        if command == "dumpsys power":
            return "mWakefulness=Awake"
        if command == "dumpsys window":
            return f"mDreamingLockscreen={'true' if self.locked else 'false'}"
        if command.startswith("pm path"):
            return f"package:/data/app/{android_tiktok.PACKAGE}/base.apk"
        if command.startswith("dumpsys activity"):
            return f"topResumedActivity={android_tiktok.PACKAGE}/Host"
        return ""

    async def open_profile(self, username: str) -> None:
        self.opened.append(username)
        self.current = username
        self.sheet = False
        # A fresh task: what the button showed without the server's say-so
        # is gone.
        self.flipped.discard(username)
        self.hidden.discard(username)

    async def dump(self) -> str:
        if self.overlay:
            return _xml([(self.overlay, "", "[0,0][1080,200]")])
        who = self.current
        if who == "gone":
            return _xml([("Couldn't find this account", "", "[0,600][1080,700]")])
        if who == self.signed_in:
            return own_profile(who)
        shown = (who in self.followed or who in self.flipped) and who not in self.hidden
        page = other_profile(who, shown, self.followers.get(who, 10))
        if self.asking:
            page = page.replace("</hierarchy>", (
                '<node text="" content-desc="Dialogue" clickable="false" bounds="[172,1139][907,1555]" />'
                '<node text="Unfollow this person? You and this person are currently friends." content-desc="" clickable="false" bounds="[225,1202][843,1376]" />'
                '<node text="Cancel" content-desc="" clickable="false" bounds="[172,1430][539,1555]" />'
                '<node text="Unfollow" content-desc="" clickable="false" bounds="[540,1430][907,1555]" />'
                "</hierarchy>"))
        if self.sheet:
            # The bottom sheet that tapping Following opens.
            page = page.replace("</hierarchy>", (
                '<node text="" content-desc="Bottom sheet" clickable="false" bounds="[0,2007][1080,2601]" />'
                '<node text="KING" content-desc="" clickable="false" bounds="[63,2049][335,2107]" />'
                '<node text="Customise name" content-desc="" clickable="false" bounds="[84,2212][865,2265]" />'
                '<node text="Unfollow" content-desc="" clickable="false" bounds="[84,2392][865,2445]" />'
                "</hierarchy>"))
        return page

    async def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        who = self.current
        if (x, y) == FOLLOWING_BUTTON and who in self.followed and not self.ignore_taps:
            self.sheet = True
            return
        if (x, y) == UNFOLLOW_ENTRY and self.sheet and self.friends:
            self.sheet = False
            self.asking = True
            return
        if ((x, y) == UNFOLLOW_ENTRY and self.sheet) or ((x, y) == FRIENDS_CONFIRM and self.asking):
            self.sheet = False
            self.asking = False
            if self.keeps_unfollow:
                self.followed.discard(who)
                self.followers[who] = self.followers.get(who, 11) - 1
            else:
                self.hidden.add(who)
            return
        if self.ignore_taps or (x, y) != FOLLOW_BUTTON:
            return
        who = self.current
        if self.phantom:
            self.flipped.add(who)
        else:
            self.followed.add(who)
            self.followers[who] = self.followers.get(who, 10) + 1

    async def screenshot(self, path: str) -> bool:
        return False


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(android_tiktok, "POLL_S", 0)
    monkeypatch.setattr(android_tiktok, "PROFILE_WAIT_S", 0.05)
    monkeypatch.setattr(android_tiktok, "CONFIRM_WAIT_S", 0.05)
    monkeypatch.setattr(android_tiktok, "DEBUG_DIR", "")


def _driver(phone: FakePhone) -> AndroidTikTokFollower:
    return AndroidTikTokFollower(adb_factory=lambda serial: phone)


ACCOUNT = {"id": 28, "platform": "tiktok",
           "device_serial": "PHONE1", "device_handle": "@" + ME}


def _target(name: str) -> dict:
    return {"username": name, "profile_url": f"https://www.tiktok.com/@{name}"}


# --- reading the screen ------------------------------------------------


def test_the_profiles_own_button_is_found_not_a_suggestion_or_a_label():
    view = read_profile(parse_nodes(other_profile("brownthickbeautiful", False, 221)))
    assert view.handle == "brownthickbeautiful"
    assert view.state == "can_follow"
    assert view.control is not None and view.control.centre == FOLLOW_BUTTON
    assert view.followers == "221"


def test_the_followed_layout_reads_as_following():
    view = read_profile(parse_nodes(other_profile("brownthickbeautiful", True, 222)))
    assert view.state == "following"
    assert view.followers == "222"
    assert not view.is_self


def test_the_signed_in_accounts_own_page_is_recognised():
    view = read_profile(parse_nodes(own_profile(ME)))
    assert view.is_self and view.handle == ME and view.state is None


def test_junk_from_adb_reads_as_nothing():
    assert parse_nodes("error: device offline") == []
    assert read_profile([]).state is None


# --- following ---------------------------------------------------------


async def test_a_follow_that_sticks_is_sent():
    phone = FakePhone()
    result = await _driver(phone).follow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.status == RESULT_SENT, result.error
    assert phone.taps == [FOLLOW_BUTTON]
    assert result.detail["followers_before"] == "221"
    assert result.detail["followers_after"] == "222"
    # Identity, the profile, and the reload — the reload is the evidence.
    assert phone.opened == [ME, "brownthickbeautiful", "brownthickbeautiful"]


async def test_a_follow_the_app_does_not_keep_is_discarded_not_sent():
    """Without the reload this reports `sent` — the web bug, on a phone."""
    phone = FakePhone(phantom=True)
    result = await _driver(phone).follow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.status == RESULT_FOLLOW_DISCARDED
    assert not result.success


async def test_a_phone_signed_in_as_someone_else_follows_nobody():
    phone = FakePhone(signed_in="somebodys_personal_account")
    result = await _driver(phone).follow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.status == RESULT_DEVICE_UNAVAILABLE
    assert "not signed in as @_lancastarmoon" in result.error
    assert phone.taps == []
    assert RESULT_DEVICE_UNAVAILABLE in IMMEDIATE_ACCOUNT_PAUSE_RESULTS


async def test_without_a_handle_nothing_is_touched():
    phone = FakePhone()
    result = await _driver(phone).follow_target(
        {**ACCOUNT, "device_handle": ""}, _target("brownthickbeautiful"))
    assert result.status == RESULT_DEVICE_UNAVAILABLE
    assert phone.opened == [] and phone.taps == []


async def test_already_following_is_done_without_a_tap():
    phone = FakePhone()
    phone.followed.add("already")
    result = await _driver(phone).follow_target(ACCOUNT, _target("already"))
    assert result.success and result.status == RESULT_ALREADY_FOLLOWING
    assert phone.taps == []


async def test_a_tap_that_changes_nothing_is_a_follow_limit():
    phone = FakePhone(ignore_taps=True)
    result = await _driver(phone).follow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.status == RESULT_FOLLOW_LIMITED


async def test_a_missing_profile_is_skipped():
    result = await _driver(FakePhone()).follow_target(ACCOUNT, _target("gone"))
    assert result.status == RESULT_PROFILE_UNAVAILABLE


async def test_a_puzzle_is_a_challenge():
    phone = FakePhone(overlay="Drag the slider to fit the puzzle")
    result = await _driver(phone).follow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.status in (RESULT_CHALLENGE_REQUIRED, RESULT_DEVICE_UNAVAILABLE)
    assert phone.taps == []


@pytest.mark.parametrize("phone", [
    FakePhone(state=""),
    FakePhone(state="unauthorized"),
    FakePhone(locked=True),
])
async def test_an_unusable_phone_pauses_the_account(phone):
    result = await _driver(phone).follow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.status == RESULT_DEVICE_UNAVAILABLE
    assert phone.taps == []


async def test_identity_is_checked_once_then_trusted_for_a_while():
    phone = FakePhone()
    driver = _driver(phone)
    await driver.follow_target(ACCOUNT, _target("brownthickbeautiful"))
    await driver.follow_target(ACCOUNT, _target("already"))
    assert phone.opened.count(ME) == 1


async def test_messages_are_not_this_drivers_job():
    result = await _driver(FakePhone()).send_message(ACCOUNT, _target("x"), "hi")
    assert not result.success


# --- routing -----------------------------------------------------------


def test_only_follows_by_an_account_with_a_phone_go_to_the_phone():
    from services.outreach.runner import OutreachWorker

    worker = OutreachWorker()
    settings = {"outreach_driver": "playwright_tiktok"}
    assert worker._driver_name_for(settings, "tiktok", via_phone=True) == "android_tiktok"
    assert worker._driver_name_for(settings, "tiktok") == "playwright_tiktok"
    # No phone driver for Instagram: its follows stay in the browser.
    assert worker._driver_name_for(settings, "instagram", via_phone=True) == \
        "playwright_instagram"
    # Mock is a promise to contact nothing, and a phone is something.
    assert worker._driver_name_for({"outreach_driver": "mock"}, "tiktok",
                                   via_phone=True) == "mock"


# --- unfollowing -------------------------------------------------------


async def test_an_unfollow_goes_through_the_sheet_and_is_checked_by_reload():
    phone = FakePhone()
    phone.followed.add("depay038")
    result = await _driver(phone).unfollow_target(ACCOUNT, _target("depay038"))
    assert result.status == RESULT_SENT, result.error
    assert phone.taps == [FOLLOWING_BUTTON, UNFOLLOW_ENTRY]
    assert "depay038" not in phone.followed
    assert phone.opened == [ME, "depay038", "depay038"]


async def test_unfollowing_someone_not_followed_touches_nothing():
    """The one thing an unfollow campaign must never do is follow."""
    phone = FakePhone()
    result = await _driver(phone).unfollow_target(ACCOUNT, _target("brownthickbeautiful"))
    assert result.success and result.status == RESULT_NOT_FOLLOWING
    assert phone.taps == []
    assert "brownthickbeautiful" not in phone.followed


async def test_an_unfollow_tiktok_does_not_keep_is_not_reported_as_done():
    phone = FakePhone(keeps_unfollow=False)
    phone.followed.add("depay038")
    result = await _driver(phone).unfollow_target(ACCOUNT, _target("depay038"))
    assert result.status == RESULT_FOLLOW_DISCARDED


async def test_unfollowing_from_the_wrong_account_is_refused():
    phone = FakePhone(signed_in="somebodys_personal_account")
    phone.followed.add("depay038")
    result = await _driver(phone).unfollow_target(ACCOUNT, _target("depay038"))
    assert result.status == RESULT_DEVICE_UNAVAILABLE
    assert phone.taps == []


async def test_unfollowing_a_friend_answers_the_second_question():
    """Mutual follows are asked twice. Without answering, nothing happens
    and it looked like a limit — measured on @depay038."""
    phone = FakePhone(friends=True)
    phone.followed.add("depay038")
    result = await _driver(phone).unfollow_target(ACCOUNT, _target("depay038"))
    assert result.status == RESULT_SENT, result.error
    assert phone.taps == [FOLLOWING_BUTTON, UNFOLLOW_ENTRY, FRIENDS_CONFIRM]
