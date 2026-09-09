"""The X driver, against a local stub — never x.com.

What this proves: that X's selector table drives the shared engine
correctly. The profile is found, the DM control is picked out without the
navigation stealing the click, the composer is typed into, delivery is
confirmed, follow-to-unlock works, and each bad page maps to the right
status.

What it cannot prove is that these selectors match the real site. X serves
nothing to a logged-out browser — a profile came back with an empty body
and a missing profile redirected to the login flow — so everything past
the wall is a hypothesis until someone runs
`scripts/verify_x_selectors.py` with a signed-in account.

The stubs copy X's real shape rather than a convenient one, because the
convenient shape is what let Instagram ship a Follow selector that matched
nothing: labels live in a nested <span> inside a <div role="button">, and
the Follow control carries the account id in its data-testid.

Skips cleanly when Playwright or its Chromium build is missing.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

playwright_api = pytest.importorskip(
    "playwright.async_api", reason="playwright is not installed"
)

from services.outreach.browser.playwright_x import (  # noqa: E402
    PlaywrightXMessenger,
)
from services.outreach.constants import (  # noqa: E402
    ACCOUNT_FAULT_RESULTS,
    RESULT_MESSAGE_REFUSED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_SENT,
    RESULT_SESSION_EXPIRED,
    TERMINAL_RESULTS,
)

# --- stub pages, using the hooks X's table looks for -----------------------

_COMPOSER = """
  <div id="chat" style="display:none">
    <div data-testid="dmComposerTextInput">
      <div contenteditable="true" role="textbox"></div>
    </div>
    <div data-testid="dmComposerSendButton" role="button" onclick="sendChat()">Send</div>
    <div data-testid="DmScrollerContainer"><div id="thread"></div></div>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function sendChat() {
      const ed = document.querySelector('[data-testid=dmComposerTextInput] [contenteditable]');
      const text = ed.innerText;
      if (!text.trim()) return;
      const row = document.createElement('div');
      row.setAttribute('data-testid', 'messageEntry');
      row.innerText = text;
      document.getElementById('thread').appendChild(row);
      fetch('/sent', { method: 'POST', body: text });
      ed.innerHTML = '';
    }
    document.addEventListener('keydown', function (e) {
      if (!e.target.closest('[data-testid=dmComposerTextInput]')) return;
      // Enter sends; Shift+Enter is left to the browser as a line break.
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
  </script>
"""

#: A profile that takes DMs. The header carries X's own test ids.
SENDABLE = f"""
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="UserProfileHeader_Items">Joined June 2011</div>
    <div data-testid="sendDMFromProfile" role="button"
         aria-label="Message @alice" onclick="openChat()">
      <span>Message</span>
    </div>
    {_COMPOSER}
  </div>
</body></html>
"""

#: X's left navigation has a "Messages" entry and the profile's own control
#: renders a beat later. This is the bug that cost a live target on TikTok.
NAV_MESSAGES_DECOY = f"""
<html><body>
  <nav><a href="/messages" role="link"><span>Messages</span></a></nav>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div id="late"></div>
    {_COMPOSER}
  </div>
  <script>
    setTimeout(function () {{
      const b = document.createElement('div');
      b.setAttribute('data-testid', 'sendDMFromProfile');
      b.setAttribute('role', 'button');
      b.setAttribute('aria-label', 'Message @alice');
      b.innerHTML = '<span>Message</span>';
      b.onclick = openChat;
      document.getElementById('late').appendChild(b);
    }}, 600);
  </script>
</body></html>
"""

#: No DM control, but a Follow button — in X's real shape, id and all.
NO_DM_BUTTON = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="99887766-follow" role="button"><span>Follow</span></div>
  </div>
</body></html>
"""

#: Not protected, but only takes DMs from people it follows. Following
#: reveals the control, in place, without a reload.
FOLLOW_UNLOCKS_DM = f"""
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div id="actions">
      <div data-testid="99887766-follow" role="button" onclick="follow()">
        <span>Follow</span>
      </div>
    </div>
    {_COMPOSER}
  </div>
  <script>
    function follow() {{
      document.getElementById('actions').innerHTML =
        '<div data-testid="99887766-unfollow" role="button"><span>Following</span></div>'
        + '<div data-testid="sendDMFromProfile" role="button" '
        + 'aria-label="Message @alice" onclick="openChat()"><span>Message</span></div>';
    }}
  </script>
</body></html>
"""

#: Protected. Follow becomes "Pending" and nothing can be sent until a
#: person accepts.
PROTECTED_ACCOUNT = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div id="actions">
      <div data-testid="99887766-follow" role="button" onclick="request()">
        <span>Follow</span>
      </div>
    </div>
  </div>
  <script>
    function request() {
      document.getElementById('actions').innerHTML =
        '<div role="button"><span>Pending</span></div>';
    }
  </script>
</body></html>
"""

#: Already followed, still no DM control. The control in that spot now
#: unfollows, and clicking it reports itself so a test can catch it.
ALREADY_FOLLOWING = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="99887766-unfollow" role="button"
         onclick="fetch('/sent', { method: 'POST', body: 'UNFOLLOWED' })">
      <span>Following</span>
    </div>
  </div>
</body></html>
"""

MISSING_PROFILE = """
<html><body><div data-testid="emptyState">This account doesn't exist</div></body></html>
"""

LOGIN_WALL = """
<html><body>
  <div data-testid="google_sign_in_container"></div>
  <span>See what's happening</span>
  <span>Select an option below</span>
</body></html>
"""

#: X takes the message, puts it in the thread, and refuses to deliver it.
SEND_REFUSED = f"""
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="sendDMFromProfile" role="button" onclick="openChat()">
      <span>Message</span>
    </div>
    {_COMPOSER.replace("fetch('/sent'", "document.getElementById('notice').style.display='block'; fetch('/sent'")}
    <div id="notice" style="display:none">Your message wasn't sent</div>
  </div>
</body></html>
"""

#: Their settings, not our account's. Must not count against the sender.
RECIPIENT_REFUSED = f"""
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="sendDMFromProfile" role="button" onclick="openChat()">
      <span>Message</span>
    </div>
    {_COMPOSER.replace("fetch('/sent'", "document.getElementById('shut').style.display='block'; fetch('/sent'")}
    <div id="shut" style="display:none">You can't send messages to this account</div>
  </div>
</body></html>
"""

PAGES = {
    "/alice": SENDABLE,
    "/navdecoy": NAV_MESSAGES_DECOY,
    "/nodm": NO_DM_BUTTON,
    "/followunlocks": FOLLOW_UNLOCKS_DM,
    "/protected": PROTECTED_ACCOUNT,
    "/following": ALREADY_FOLLOWING,
    "/gone": MISSING_PROFILE,
    "/loggedout": LOGIN_WALL,
    "/refused": SEND_REFUSED,
    "/shut": RECIPIENT_REFUSED,
}

RECEIVED: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's interface
        body = PAGES.get(self.path, "<html><body>not found</body></html>")
        # Serve back what was submitted: the engine confirms a send by
        # reloading, so a stub that stores nothing would fail every send.
        if '<div id="thread"></div>' in body:
            rows = "".join(
                f'<div data-testid="messageEntry">{m}</div>' for m in RECEIVED
            )
            body = body.replace('<div id="thread"></div>', f'<div id="thread">{rows}</div>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        RECEIVED.append(self.rfile.read(length).decode())
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):  # noqa: A003 — silence the test server
        return


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    RECEIVED.clear()
    monkeypatch.setattr("services.outreach.browser.playwright_base.DEBUG_DIR", "")
    for name, value in (
        ("PROFILE_READY_MS", 800), ("MESSAGE_BUTTON_MS", 2000), ("CLICK_MS", 2000),
        ("COMPOSER_MS", 2000), ("SETTLE_MS", 300), ("FOLLOW_UNLOCK_MS", 2000),
        ("CONFIRM_RENDER_MS", 1000),
    ):
        monkeypatch.setattr(f"services.outreach.browser.playwright_base.{name}", value)


@pytest.fixture
async def driver():
    messenger = PlaywrightXMessenger(headless=True, timeout_ms=8000)
    try:
        await messenger.startup()
    except Exception as exc:  # noqa: BLE001 — no browser binary in this env
        pytest.skip(f"Chromium is not available: {exc}")
    try:
        yield messenger
    finally:
        await messenger.shutdown()


def account(account_id: int = 1) -> dict:
    return {
        "id": account_id,
        "name": "Sender 1",
        "platform": "x",
        "session_state": json.dumps({"cookies": [], "origins": []}),
    }


def target(
    site: str, path: str, username: str = "alice", follow_to_unlock: bool = True
) -> dict:
    return {
        "username": username,
        "profile_url": f"{site}{path}",
        "follow_to_unlock": follow_to_unlock,
    }


# --- the shared engine, driven by X's table --------------------------------

async def test_sends_and_confirms_delivery(driver, site):
    message = "Hi alice, loved the last post."
    result = await driver.send_message(account(), target(site, "/alice"), message)

    assert result.success is True, result.error
    assert result.status == RESULT_SENT
    # What the page actually received, not what the driver believed.
    assert RECEIVED == [message]


async def test_a_line_break_stays_inside_one_message(driver, site):
    """Enter sends in X's composer, as in every other chat box on the web.

    A two-line template arrived as two messages on Instagram before this
    was fixed in the engine; the same composer behaviour is stubbed here so
    X cannot quietly regress it.
    """
    message = "We ship to USA only!\nask us how to get a free sample!"
    result = await driver.send_message(account(), target(site, "/alice"), message)

    assert result.success is True, result.error
    assert RECEIVED == [message], f"expected one message, got {RECEIVED!r}"


async def test_the_navigation_messages_link_cannot_win(driver, site):
    """X's nav has a "Messages" entry and the profile's control renders late.

    This is the bug that cost a live target on TikTok, so X's generic tier
    matches an aria-label rather than the word "Message" anywhere.
    """
    message = "Hi alice, quick question."
    result = await driver.send_message(account(), target(site, "/navdecoy"), message)
    assert result.success is True, result.error
    assert RECEIVED == [message]


async def test_a_profile_without_a_dm_control_is_not_permanent(driver, site):
    """No DM control is inferred from an absence, and absence has too many
    innocent causes to write a target off for good."""
    result = await driver.send_message(account(), target(site, "/nodm"), "Hi alice.")
    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert result.status not in TERMINAL_RESULTS
    assert RECEIVED == []


async def test_a_missing_profile_is_reported_as_such(driver, site):
    result = await driver.send_message(account(), target(site, "/gone"), "Hi alice.")
    assert result.success is False
    assert RECEIVED == []


async def test_a_login_wall_is_an_expired_session(driver, site):
    """The one part of X's table measured against the live site: logged
    out, every URL lands on this flow."""
    result = await driver.send_message(account(), target(site, "/loggedout"), "Hi.")
    assert result.success is False
    assert result.status == RESULT_SESSION_EXPIRED


async def test_a_refused_message_is_not_reported_as_sent(driver, site):
    result = await driver.send_message(account(), target(site, "/refused"), "Hi alice.")
    assert result.success is False
    assert result.status == RESULT_MESSAGE_REFUSED


async def test_a_recipient_who_refuses_does_not_blame_the_account(driver, site):
    """Their settings, not ours.

    Counting this against the sending account's error budget would pause a
    healthy account because a few strangers keep their inbox closed.
    """
    result = await driver.send_message(account(), target(site, "/shut"), "Hi alice.")
    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert result.status not in ACCOUNT_FAULT_RESULTS


# --- following to unlock the DM control ------------------------------------

async def test_following_reveals_the_dm_control_and_the_send_continues(driver, site):
    message = "Hi alice, quick question."
    result = await driver.send_message(
        account(), target(site, "/followunlocks"), message
    )
    assert result.success is True, result.error
    assert RECEIVED == [message]


async def test_a_protected_account_is_requested_and_left_alone(driver, site):
    """Follow becomes "Pending" and nothing else happens.

    Nothing can be sent until a person accepts, so there is nothing to wait
    for on this visit — and it must not be reported as a send.
    """
    result = await driver.send_message(account(), target(site, "/protected"), "Hi.")
    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert RECEIVED == []


async def test_an_account_already_followed_is_never_clicked_again(driver, site):
    """The control that unfollows people says "Following".

    X flips the same element's data-testid from `-follow` to `-unfollow`,
    so the suffix match is what keeps these apart.
    """
    result = await driver.send_message(account(), target(site, "/following"), "Hi.")
    assert result.success is False
    assert RECEIVED == [], f"the Following control was clicked: {RECEIVED!r}"


# --- the selector traps, pinned --------------------------------------------

def test_the_follow_selector_cannot_match_a_following_button():
    """Both ways of getting this wrong, learned on Instagram.

    `:has-text('Follow')` is a substring and matches the *Following*
    button, which unfollows someone on every target. `:text-is('Follow')`
    matches the smallest element holding the text — the inner span, never
    the button — so it matches nothing at all and no follow ever happens.
    X nests its labels in spans exactly as Instagram does, so both traps
    are live here.
    """
    flat = " ".join(
        selector
        for tier in PlaywrightXMessenger.SELECTORS["follow_button"]
        for selector in tier
    )
    assert ":has-text(" not in flat, (
        "a substring match here matches 'Following' and unfollows people"
    )
    assert "span:text-is('Follow')" in flat, (
        "the label is a span inside the button, so the match has to be "
        "ancestor-aware and exact at the same time"
    )
    assert "[data-testid$='-follow']" in flat, (
        "X carries the account id in the test id, so the suffix is what "
        "separates -follow from -unfollow"
    )


def test_a_handle_is_one_segment_of_the_right_shape():
    """X's chrome is full of links that look like profiles."""
    d = PlaywrightXMessenger
    assert d.username_from_url(d, "/nasa") == "nasa"
    assert d.username_from_url(d, "https://x.com/nasa?lang=en") == "nasa"
    for junk in ("/home", "/i/flow/login", "/nasa/status/123", "/explore",
                 "/hashtag/space", "/messages", "", "/wayyyytoolongahandle"):
        assert d.username_from_url(d, junk) == "", junk
