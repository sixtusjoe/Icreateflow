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
import time
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

#: Revisiting a protected account whose follow request is already in. X
#: does not reuse the `-follow` testid for this: the control becomes
#: `<userid>-cancel`, which cancels the request.
PENDING_REQUEST = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="99887766-cancel" role="button"
         onclick="fetch('/sent', { method: 'POST', body: 'CANCELLED' })">
      <span>Pending</span>
    </div>
    <p>These posts are protected</p>
  </div>
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

#: X's own words, from a live send. The message is in the thread; what X
#: is saying is that it will not land in their inbox.
NEEDS_X_NUMBER = f"""
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="sendDMFromProfile" role="button" onclick="openChat()">
      <span>Message</span>
    </div>
    {_COMPOSER.replace("fetch('/sent'", "document.getElementById('nx').style.display='block'; fetch('/sent'")}
    <div id="nx" style="display:none">
      @alice doesn't follow you. If you know their X Number you can reach
      their inbox directly.
      <div role="button">Enter X Number</div>
    </div>
  </div>
</body></html>
"""

#: The passcode screen, as the reload after a send lands on it. The
#: message went; the conversation is simply not shown to a browser that
#: has not been unlocked.
LOCKED_AFTER_SEND = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="sendDMFromProfile" role="button" onclick="openChat()">
      <span>Message</span>
    </div>
    <div id="chat" style="display:none">
      <div data-testid="dm-composer-textarea-wrap">
        <textarea data-testid="dm-composer-textarea"></textarea>
      </div>
      <div data-testid="dm-composer-send-button" role="button" onclick="sendChat()">Send</div>
      <div data-testid="dm-message-list"><div id="thread"></div></div>
    </div>
    <script>
      function openChat() { document.getElementById('chat').style.display = 'block'; }
      function sendChat() {
        const ed = document.querySelector("[data-testid='dm-composer-textarea']");
        const row = document.createElement('div');
        row.innerText = ed.value;
        document.getElementById('thread').appendChild(row);
        fetch('/sent', { method: 'POST', body: ed.value });
        ed.value = '';
        // The reload lands on the passcode screen, so mark the server.
        fetch('/lock', { method: 'POST', body: 'locked' });
      }
    </script>
  </div>
</body></html>
"""

PASSCODE_SCREEN = """
<html><body>
  <div data-testid="pin-code-input-container"></div>
  <div data-testid="pin-title">Enter Passcode</div>
  <p>Your passcode is required to recover your encryption keys so we can
     decrypt your previous messages.</p>
</body></html>
"""

#: A locked DM: the Message control is there, clicking it opens nothing,
#: and X says why straight away. The composer never appears at all.
LOCKED_DM = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div data-testid="sendDMFromProfile" role="button" onclick="block()">
      <span>Message</span>
    </div>
    <div id="why" style="display:none">
      @alice has a closed inbox. If you know their X Number you can still
      message them.
    </div>
  </div>
  <script>
    function block() { document.getElementById('why').style.display = 'block'; }
  </script>
</body></html>
"""

#: A likes list the way X serves one: it recycles its rows, so scrolling
#: past a name destroys it, and each page of names arrives a beat after the
#: scroll that asked for it.
RECYCLING_LIKES = """
<html><body>
  <div data-testid="primaryColumn" style="height:200px;overflow:auto"
       onscroll="render()">
    <div id="spacer" style="position:relative"><div id="rows"></div></div>
  </div>
  <script>
    const ROW_H = 40, WINDOW = 5, TOTAL = 50;
    let loaded = 10;                       // how many the server has sent
    const NAMES = [];
    for (let i = 0; i < TOTAL; i++) NAMES.push('liker' + i);
    function render() {
      const box = document.querySelector("[data-testid='primaryColumn']");
      document.getElementById('spacer').style.height = (loaded * ROW_H) + 'px';
      const first = Math.floor(box.scrollTop / ROW_H);
      const last = Math.min(first + WINDOW, loaded);
      let html = '';
      for (let i = first; i < last; i++) {
        html += '<div data-testid="UserCell" style="position:absolute;top:'
             + (i * ROW_H) + 'px"><a href="/' + NAMES[i] + '">'
             + NAMES[i] + '</a></div>';
      }
      document.getElementById('rows').innerHTML = html;
      // Near the bottom? Fetch the next page — after a delay, as a real
      // one does.
      if (last >= loaded && loaded < TOTAL) {
        setTimeout(() => { loaded = Math.min(loaded + 10, TOTAL); render(); }, 900);
      }
    }
    render();
  </script>
</body></html>
"""

#: A profile whose header re-renders shortly after load, the way X's does
#: while it hydrates. The re-render replaces the button node, so anything
#: written onto the old node by script is gone.
RERENDERING_HEADER = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <div id="slot">
      <button data-testid="99887766-follow" onclick="fetch('/sent',{method:'POST',body:'FOLLOWED'})">
        <span>Follow</span></button>
    </div>
    <div data-testid="UserCell">
      <button data-testid="11110000-follow"><span>Follow</span></button>
    </div>
  </div>
  <script>
    // React-style: throw the node away and build a fresh one.
    setTimeout(() => {
      document.getElementById('slot').innerHTML =
        '<button data-testid="99887766-follow" '
        + "onclick=\"fetch('/sent',{method:'POST',body:'FOLLOWED'})\">"
        + '<span>Follow</span></button>';
    }, 700);
  </script>
</body></html>
"""

#: A profile whose Follow button never settles — X animates it while the
#: header hydrates. Playwright's actionability check waits for the element
#: to hold still, so an ordinary click can never fire on one of these.
RESTLESS_FOLLOW = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <button id="f" data-testid="99887766-follow" style="position:relative"
            onclick="took()"><span>Follow</span></button>
  </div>
  <script>
    // Never stops moving: the stability check cannot pass.
    let n = 0;
    setInterval(() => { n = (n + 1) % 8;
      document.getElementById('f').style.left = n + 'px'; }, 30);
    function took() {
      const b = document.getElementById('f');
      b.setAttribute('data-testid', '99887766-unfollow');
      b.innerHTML = '<span>Following</span>';
      fetch('/sent', { method: 'POST', body: 'FOLLOWED' });
    }
  </script>
</body></html>
"""

#: An ordinary profile that can be followed, in X's markup: the button
#: carries `<userid>-follow` and flips to `-unfollow` once pressed.
X_FOLLOWABLE = """
<html><body>
  <div data-testid="primaryColumn">
    <div data-testid="UserName"><span>Alice</span><span>@alice</span></div>
    <button id="f" data-testid="99887766-follow" onclick="took()">
      <span>Follow</span></button>
    <div data-testid="UserCell">
      <button data-testid="11110000-follow"><span>Follow</span></button>
    </div>
  </div>
  <script>
    function took() {
      const b = document.getElementById('f');
      b.setAttribute('data-testid', '99887766-unfollow');
      b.innerHTML = '<span>Following</span>';
      fetch('/sent', { method: 'POST', body: 'FOLLOWED' });
    }
  </script>
</body></html>
"""

PAGES = {
    "/xfollowable": X_FOLLOWABLE,

    "/restless": RESTLESS_FOLLOW,

    "/rerender": RERENDERING_HEADER,

    "/recyclinglikes": RECYCLING_LIKES,

    "/alice": SENDABLE,
    "/lockeddm": LOCKED_DM,
    "/needsxnumber": NEEDS_X_NUMBER,
    "/locked": LOCKED_AFTER_SEND,
    "/navdecoy": NAV_MESSAGES_DECOY,
    "/nodm": NO_DM_BUTTON,
    "/followunlocks": FOLLOW_UNLOCKS_DM,
    "/protected": PROTECTED_ACCOUNT,
    "/pending": PENDING_REQUEST,
    "/following": ALREADY_FOLLOWING,
    "/gone": MISSING_PROFILE,
    "/loggedout": LOGIN_WALL,
    "/refused": SEND_REFUSED,
    "/shut": RECIPIENT_REFUSED,
}

RECEIVED: list[str] = []
#: Set once a send has happened on `/locked`, so the reload behaves as X does.
LOCKED: list[bool] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's interface
        if self.path == "/locked" and LOCKED:
            # The reload after a send: X shows the passcode prompt, not the
            # conversation.
            body = PASSCODE_SCREEN
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
            return
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
        payload = self.rfile.read(length).decode()
        if self.path == "/lock":
            LOCKED.append(True)
            self.send_response(204)
            self.end_headers()
            return
        RECEIVED.append(payload)
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
    LOCKED.clear()
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


# --- telling the failures apart --------------------------------------------

async def test_the_x_number_notice_is_a_delivery_not_a_refusal(driver, site):
    """"Doesn't follow you" reads like a block and is not one.

    X shows it beside a message it has already delivered, with the composer
    still underneath: the message goes to their requests rather than their
    inbox, and X is offering a second route to the inbox on top.

    Verified live on @cherykang — the message was in the thread at 8:03,
    the conversation list read "You: Hello", and this notice was on screen
    throughout. It was briefly filed as a recipient block, which marked
    delivered messages as failures and left them queued to be sent a second
    time.
    """
    message = "Hello"
    result = await driver.send_message(
        account(), target(site, "/needsxnumber"), message
    )

    assert RECEIVED == [message], f"the message should have gone: {RECEIVED!r}"
    assert result.success is True, result.error
    assert result.status == RESULT_SENT


def test_the_x_number_notice_is_not_in_the_block_table():
    """The distinction, pinned where it would be undone.

    A closed inbox replaces the composer and nothing is sent. This notice
    sits beside a working composer and a delivered message. They look
    similar enough in X's wording that grouping them is the obvious
    mistake — it is the one that was made.
    """
    keys = [key for key, _ in PlaywrightXMessenger.RECIPIENT_BLOCKS]
    assert "x_inbox_closed" in keys
    assert "x_number_required" not in keys, (
        "this notice appears on delivered messages; blocking on it fails "
        "sends that worked"
    )


async def test_a_locked_thread_is_not_a_lost_message(driver, site):
    """The eight identical errors that were not identical.

    X asks for its encryption passcode once per browser, and a worker
    starting from a stored session has not given it — so the reload after a
    send lands on "Enter Passcode" and the conversation is shown to nobody.
    Reading that as "the platform did not keep it" turned messages that had
    demonstrably arrived into failures, and queued them to be sent again.
    """
    message = "Hello"

    result = await driver.send_message(account(), target(site, "/locked"), message)

    assert RECEIVED == [message], f"the send itself should have happened: {RECEIVED!r}"
    assert result.success is True, result.error
    assert result.status == RESULT_SENT


def test_the_recipient_blocks_are_ordered_most_specific_first():
    """Both mean "cannot be reached"; only one of them is the target's doing.

    If the generic refusal were checked first it would match nothing here,
    but the ordering is the thing that keeps the specific answer from being
    swallowed by the general one as more are added.
    """
    keys = [key for key, _ in PlaywrightXMessenger.RECIPIENT_BLOCKS]
    assert keys.index("x_inbox_closed") < keys.index("recipient_refused")
    for key, reason in PlaywrightXMessenger.RECIPIENT_BLOCKS:
        assert PlaywrightXMessenger.SELECTORS.get(key), f"{key} has no selectors"
        assert reason and not reason.endswith("."), reason


async def test_a_locked_dm_does_not_wait_out_the_composer_budget(driver, site):
    """The answer is on screen; waiting thirty seconds for it is not free.

    X replaces the composer with "has a closed inbox" the moment Message is
    clicked, and the wait then sat there for the full composer budget with
    the reason already rendered. On a run where most profiles are locked
    that is nearly all of the time spent.

    The budget here is deliberately left at its real value rather than
    monkeypatched down: the point is that it is not spent.
    """
    driver.COMPOSER_TIMEOUT_MS = 20000

    started = time.monotonic()
    result = await driver.send_message(account(), target(site, "/lockeddm"), "Hello")
    took = time.monotonic() - started

    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert "closed inbox" in (result.error or ""), result.error
    assert RECEIVED == []
    assert took < 12, (
        f"took {took:.0f}s against a 20s composer budget — the wait is still "
        f"being paid in full"
    )


async def test_a_follow_request_already_in_reads_as_pending(driver, site):
    """A sent follow request is not "this profile has no follow button".

    X gives the pending control its own testid — `<userid>-cancel`, the
    one that withdraws the request — and the probe matched only `-follow`
    and `-unfollow`. So every protected account we had already requested
    came back as having no follow control at all.

    That reads as a profile that cannot be followed, which is the opposite
    of the truth: the request went in and is waiting on a person. Sixteen
    accounts were logged that way across one run, and re-running could not
    tell them from genuine dead ends.

    Matching `-cancel` is also what stops it being clicked: the control
    under the cursor cancels the request we just made.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    await page.goto(f"{site}/pending", wait_until="domcontentloaded")
    state, locator = await driver._profile_follow_control(page)
    assert state == "pending", f"read as {state!r}"
    assert locator is not None
    await page.close()
    assert RECEIVED == [], "the pending control was clicked — that cancels it"


def test_the_likes_list_is_asked_for_the_way_x_names_it():
    """X's likers live at /likes, not Instagram's /liked_by/.

    The base builds the Instagram form, so X inherited a URL that is not a
    page on x.com — asking for it returns the post, whose own markup then
    yields the author and the repliers rather than the likers. That reads
    as "this post has few likers" instead of "we asked the wrong question".
    """
    # No browser is started: the constructor only records settings.
    d = PlaywrightXMessenger(headless=True)
    url = d._likers_url("https://x.com/kuppy/status/123")
    assert url.endswith("/likes"), url
    assert "liked_by" not in url
    # And it must not double up when the caller already passed the slash.
    assert d._likers_url("https://x.com/kuppy/status/123/") == url
    # A bare path is made absolute against x.com.
    assert d._likers_url("/kuppy/status/123").startswith("http")


async def test_a_recycling_list_is_read_all_the_way_down(driver, site):
    """Everyone on the list, not whoever survived the last scroll.

    `_profile_links` kept only what was rendered at that moment and
    replaced it each round, so a list that recycles its rows — X's does —
    could come back *smaller* after a scroll. That also tripped the exit,
    which fired on the first round that did not grow, with no allowance for
    a page of names still in flight.

    Measured on live posts by an account with 180.7K followers: five to
    fifteen engaged people per post.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    names = await driver._profile_links(
        page, f"{site}/recyclinglikes",
        ("[data-testid='primaryColumn'] [data-testid='UserCell'] a[href^='/']",),
        scroll_rounds=40,
    )
    await page.close()
    found = {n for n in names if n.startswith("liker")}
    missing = {f"liker{i}" for i in range(50)} - found
    assert not missing, f"{len(missing)} of 50 were never read: {sorted(missing)[:6]}"


async def test_the_follow_control_survives_a_header_re_render(driver, site):
    """The handle on the button must outlive X rebuilding the header.

    The control was found by writing `data-icf-own-follow` onto the element
    and then clicking that attribute. X re-renders the profile header while
    it hydrates, and a re-render replaces the node — taking the attribute
    with it. The locator then matched nothing and the click sat waiting for
    an element that no longer existed, for its whole eight-second budget.

    Live, that was roughly half of every attempt: 6, 9 and 9 TimeoutErrors
    against 9, 6 and 5 follows across three accounts. Indistinguishable
    from a rate limit, and it was read as one.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    await page.goto(f"{site}/rerender", wait_until="domcontentloaded")
    state, locator = await driver._profile_follow_control(page)
    assert state == "can_follow", state
    # The header is rebuilt underneath us, exactly as X does.
    await page.wait_for_timeout(1400)
    await locator.click(timeout=3000)
    await page.wait_for_timeout(400)
    await page.close()
    assert RECEIVED == ["FOLLOWED"], (
        f"the click never reached the button: {RECEIVED!r}"
    )


async def test_follow_target_reports_a_follow_it_actually_made(driver, site):
    """A follow is only a follow once the button says so."""
    result = await driver.follow_target(account(), target(site, "/xfollowable"))
    assert result.success is True, result.error
    assert result.status == RESULT_SENT


async def test_follow_target_does_not_touch_an_account_already_followed(driver, site):
    """The control that unfollows people looks just like the one that follows.

    Clicking it here would undo a follow rather than make one.
    """
    result = await driver.follow_target(account(), target(site, "/following"))
    assert result.success is True
    assert "already" in (result.error or "").lower() or result.status == RESULT_SENT
    assert RECEIVED == [], f"the Following control was clicked: {RECEIVED!r}"


async def test_follow_target_clicks_a_button_that_will_not_hold_still(driver, site):
    """X animates the button while the header hydrates.

    Playwright refuses to click until an element is stable, so the ordinary
    path can never fire on these — live, that was the profiles the operator
    had to click by hand. A real mouse press at its coordinates asks for no
    such guarantee.
    """
    result = await driver.follow_target(account(), target(site, "/restless"))
    assert result.success is True, result.error
    assert RECEIVED == ["FOLLOWED"], (
        f"the restless button was never actually pressed: {RECEIVED!r}"
    )
