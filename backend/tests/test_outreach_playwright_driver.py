"""Playwright driver mechanics, against a local stub — never TikTok.

This does not and cannot prove the real selectors still match tiktok.com; only
running it against the live site does that. What it proves is everything else,
which is where driver bugs actually live: that a `BrowserContext` is created
per account and kept between jobs, that a stored session is loaded, that the
composer is found, typed into and submitted, that delivery is verified before
success is reported, and that each bad-page state maps to the right
`MessageResult` status instead of an exception.

Skips cleanly when Playwright or its Chromium build is not installed, so the
normal suite runs without a browser.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

playwright_api = pytest.importorskip(
    "playwright.async_api", reason="playwright is not installed"
)

from services.outreach.browser.playwright_tiktok import (  # noqa: E402
    PlaywrightTikTokMessenger,
)
from services.outreach.constants import (  # noqa: E402
    ACCOUNT_FAULT_RESULTS,
    IMMEDIATE_ACCOUNT_PAUSE_RESULTS,
    RESULT_ABORTED,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SENT,
    RESULT_SESSION_EXPIRED,
    RESULT_UNEXPECTED_PAGE,
    TERMINAL_RESULTS,
)

# --- stub pages, using the same data-e2e hooks the driver looks for ---------

SENDABLE = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <button data-e2e="message-button" onclick="openChat()">Message</button>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.setAttribute('data-e2e', 'chat-item');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      // Report what was really typed so a test can assert on it after the
      // driver has closed the page.
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

NO_MESSAGE_BUTTON = """
<html><body><div data-e2e="user-title">@alice</div><p>No DMs here.</p></body></html>
"""

MISSING_PROFILE = "<html><body><p>Couldn't find this account</p></body></html>"

LOGIN_WALL = """
<html><body><button data-e2e="login-button">Log in</button></body></html>
"""

RATE_LIMITED = "<html><body><p>You're sending messages too fast</p></body></html>"

# Button is there, but clicking it opens nothing — the shape a redesign takes.
COMPOSER_NEVER_OPENS = """
<html><body>
  <button data-e2e="message-button">Message</button>
</body></html>
"""

# Clicking send does nothing at all: the text stays in the composer. This is
# what a real failed send looks like — and exactly what the original
# "is the message text anywhere on the page?" check reported as delivered,
# because the composer is part of the page.
SEND_SILENTLY_FAILS = """
<html><body>
  <button data-e2e="message-button" onclick="openChat()">Message</button>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
  </script>
</body></html>
"""

# The composer clears but the message never appears in the conversation —
# the other half of "cleared" not being proof on its own.
SEND_SWALLOWS_MESSAGE = """
<html><body>
  <button data-e2e="message-button" onclick="openChat()">Message</button>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="swallow()">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function swallow() {
      document.querySelector('[data-e2e="message-input-area"]').innerText = '';
    }
  </script>
</body></html>
"""

# A profile whose message entry point has been renamed — the shape a TikTok
# redesign takes. The driver can't send, but it should report what the page
# *does* offer so the new selector is obvious from the log.
RENAMED_MESSAGE_BUTTON = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <button data-e2e="follow-button">Follow</button>
  <button data-e2e="dm-entry">Chat</button>
</body></html>
"""

# The Message control as a div, which is how TikTok actually builds it —
# the shape that made a real profile report "no Message button".
DIV_MESSAGE_BUTTON = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <div role="button">Message</div>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    document.querySelector('div[role=button]').onclick =
      () => { document.getElementById('chat').style.display = 'block'; };
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

# A nav "Messages" entry alongside the real control, to prove the loose
# selector cannot win the race against the specific one.
NAV_DECOY = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <a role="button" href="/messages">Messages</a>
  <div data-e2e="message-button">Message</div>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    document.querySelector('[data-e2e=message-button]').onclick =
      () => { document.getElementById('chat').style.display = 'block'; };
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

# A consent banner laid over the whole page. Playwright's click waits for
# the target to receive pointer events, so the button underneath is
# unclickable until the banner goes — which is what a 30s click timeout on
# a button that is plainly visible actually means.
OVERLAY_BLOCKS_BUTTON = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <div data-e2e="message-button">Message</div>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <div id="cookie" style="position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.6)">
    <button onclick="document.getElementById('cookie').remove()">Decline all</button>
  </div>
  <script>
    document.querySelector('[data-e2e=message-button]').onclick =
      () => { document.getElementById('chat').style.display = 'block'; };
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

# A nav "Messages" entry on a profile whose real control has no data-e2e
# hook and renders a beat late — the exact shape that broke in production.
# `:has-text('Message')` matches the word inside "Messages", so the loose
# tier could win the race against a button that isn't in the DOM yet, click
# the nav link, and land on the inbox with nothing to type into.
NAV_MESSAGES_DECOY = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <a role="button" href="/inboxempty">Messages</a>
  <div id="late"></div>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    setTimeout(() => {
      const real = document.createElement('div');
      real.setAttribute('role', 'button');
      real.textContent = 'Message';
      real.onclick = () => { document.getElementById('chat').style.display = 'block'; };
      document.getElementById('late').appendChild(real);
    }, 400);
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

# Clicking Message hands off to the messages app rather than opening a box
# in place — TikTok's real behaviour, and why the driver has to cope with
# arriving at a conversation list instead of a composer.
INBOX_HANDOFF = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <div data-e2e="message-button" onclick="location.href='/inboxlist'">Message</div>
</body></html>
"""

# The same hand-off, landing in an inbox that has no thread for the target.
INBOX_HANDOFF_MISS = INBOX_HANDOFF.replace("/inboxlist", "/inboxempty")


def _inbox(*names: str) -> str:
    """An inbox page listing `names` as conversations, none of them open.

    The composer only appears once a row is clicked, and what it submits is
    tagged with the thread it went to — so a test can prove not just that
    something was sent, but that it was sent to the right person.
    """
    rows = "".join(
        f"""<div data-e2e="chat-list-item" onclick="openThread('{name}')">
              <span data-e2e="inbox-title">{name}</span>
            </div>"""
        for name in names
    )
    return f"""
<html><body>
  <div data-e2e="chat-list">{rows}</div>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <script>
    let current = null;
    function openThread(name) {{
      current = name;
      document.getElementById('chat').style.display = 'block';
    }}
    function sendChat() {{
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', {{ method: 'POST', body: current + '|' + ed.innerText }});
      ed.innerText = '';
    }}
  </script>
</body></html>
"""


#: The puzzle sitting on top of an otherwise normal, sendable profile —
#: what production actually hit. The Message button is present and visible,
#: so every page-state check passes; the overlay just eats the click.
CAPTCHA_OVER_PROFILE = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <button data-e2e="message-button" onclick="openChat()">Message</button>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send">Send</button>
  </div>
  <div id="captcha-verify-container"
       style="position:fixed;top:0;left:0;width:100%;height:100%;background:#222;z-index:99">
    <p>Drag the slider to fit the puzzle</p>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
  </script>
</body></html>
"""

#: The same challenge, but thrown before the profile's controls render — so
#: there is no Message button to find at all. This is the damaging one: the
#: driver used to call this "does not accept DMs", which is terminal, and
#: the target was skipped permanently over a puzzle nobody was asked to solve.
CAPTCHA_INSTEAD_OF_CONTROLS = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <div id="captcha-verify-container">
    <p>Drag the slider to fit the puzzle</p>
  </div>
</body></html>
"""

#: The challenge served in an iframe, which is how TikTok normally does it.
#: The top document has nothing clickable on it whatsoever — this is the
#: `page offers: []` seen in the worker log — and `page.locator` does not
#: descend into frames, so a selector-only check sees a healthy blank page.
CAPTCHA_IN_FRAME = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <iframe src="/captcha-verify-inner" style="width:400px;height:300px"></iframe>
</body></html>
"""

#: The puzzle a person then solves. It clears itself after a beat, standing
#: in for somebody dragging the slider in the VNC window — after which the
#: profile underneath is perfectly sendable.
CAPTCHA_THEN_SOLVED = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <button data-e2e="message-button" onclick="openChat()">Message</button>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <div id="captcha-verify-container"
       style="position:fixed;top:0;left:0;width:100%;height:100%;background:#222;z-index:99">
    <p>Drag the slider to fit the puzzle</p>
  </div>
  <script>
    setTimeout(function () {
      document.getElementById('captcha-verify-container').remove();
    }, 1500);
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.setAttribute('data-e2e', 'chat-item');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

#: The puzzle that *eats the click*. Clicking Message throws the challenge
#: instead of opening the composer, then the challenge clears — leaving a
#: healthy profile, an untouched Message button and no composer. This is
#: what live TikTok did twice: "puzzle cleared — carrying on" followed
#: immediately by "composer never opened".
CAPTCHA_EATS_THE_CLICK = """
<html><body>
  <div data-e2e="user-title">@alice</div>
  <button data-e2e="message-button" onclick="onMessage()">Message</button>
  <div id="chat" style="display:none">
    <div data-e2e="message-input-area" contenteditable="true" role="textbox"></div>
    <button data-e2e="message-send" onclick="sendChat()">Send</button>
    <div id="thread"></div>
  </div>
  <div id="captcha-verify-container"
       style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:#222;z-index:99">
    <p>Drag the slider to fit the puzzle</p>
  </div>
  <script>
    let swallowed = false;
    function onMessage() {
      if (!swallowed) {
        swallowed = true;
        const c = document.getElementById('captcha-verify-container');
        c.style.display = 'block';
        setTimeout(function () { c.remove(); }, 1500);
        return;
      }
      document.getElementById('chat').style.display = 'block';
    }
    function sendChat() {
      const ed = document.querySelector('[data-e2e="message-input-area"]');
      const item = document.createElement('div');
      item.setAttribute('data-e2e', 'chat-item');
      item.textContent = ed.innerText;
      document.getElementById('thread').appendChild(item);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

CAPTCHA_FRAME_INNER = """
<html><body><p>Drag the slider to fit the puzzle</p></body></html>
"""


PAGES = {
    "/alice": SENDABLE,
    "/captcha": CAPTCHA_OVER_PROFILE,
    "/captchaonly": CAPTCHA_INSTEAD_OF_CONTROLS,
    "/captchaframe": CAPTCHA_IN_FRAME,
    "/captchaclears": CAPTCHA_THEN_SOLVED,
    "/captchaeatsclick": CAPTCHA_EATS_THE_CLICK,
    "/captcha-verify-inner": CAPTCHA_FRAME_INNER,
    "/navmessages": NAV_MESSAGES_DECOY,
    "/inbox": INBOX_HANDOFF,
    "/inboxmiss": INBOX_HANDOFF_MISS,
    "/inboxlist": _inbox("Pain", "alice", "Véronique koumassa"),
    # The same hand-off, but this account has never spoken to the target, so
    # there is no thread to fall back on.
    "/inboxempty": _inbox("Pain", "Véronique koumassa"),
    "/overlay": OVERLAY_BLOCKS_BUTTON,
    "/divbutton": DIV_MESSAGE_BUTTON,
    "/navdecoy": NAV_DECOY,
    "/renamed": RENAMED_MESSAGE_BUTTON,
    "/silentfail": SEND_SILENTLY_FAILS,
    "/swallowed": SEND_SWALLOWS_MESSAGE,
    "/bob": SENDABLE,
    "/nodm": NO_MESSAGE_BUTTON,
    "/gone": MISSING_PROFILE,
    "/loggedout": LOGIN_WALL,
    "/throttled": RATE_LIMITED,
    "/redesigned": COMPOSER_NEVER_OPENS,
}


#: Message bodies the stub page reported as actually submitted.
RECEIVED: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's interface
        body = PAGES.get(self.path, "<html><body>not found</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        RECEIVED.append(self.rfile.read(length).decode())
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *args):  # silence the per-request stderr logging
        pass


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
def clear_received(monkeypatch):
    RECEIVED.clear()
    # No screenshots from the test suite.
    monkeypatch.setattr(
        "services.outreach.browser.playwright_tiktok.DEBUG_DIR", "", raising=False
    )
    # The production budgets assume a cold server rendering a real profile.
    # A local stub renders instantly, so the negative cases would otherwise
    # just sit waiting them out.
    for name, value in (
        ("PROFILE_READY_MS", 500), ("MESSAGE_BUTTON_MS", 1500), ("CLICK_MS", 2000),
        ("COMPOSER_MS", 1500),
    ):
        monkeypatch.setattr(
            f"services.outreach.browser.playwright_tiktok.{name}", value, raising=False
        )


@pytest.fixture
async def driver():
    messenger = PlaywrightTikTokMessenger(headless=True, timeout_ms=8000)
    try:
        await messenger.startup()
    except Exception as exc:  # noqa: BLE001 — no browser binary in this env
        pytest.skip(f"Chromium is not available: {exc}")
    try:
        yield messenger
    finally:
        await messenger.shutdown()


def account(account_id: int = 1, name: str = "Sender 1", session: bool = True) -> dict:
    return {
        "id": account_id,
        "name": name,
        "platform": "tiktok",
        "session_state": json.dumps({"cookies": [], "origins": []}) if session else None,
    }


def target(site: str, path: str, username: str = "alice") -> dict:
    return {"username": username, "profile_url": f"{site}{path}"}


# --- the happy path --------------------------------------------------------

async def test_sends_a_message_and_verifies_delivery(driver, site):
    result = await driver.send_message(
        account(), target(site, "/alice"), "Hello alice, quick question."
    )
    assert result.success is True
    assert result.status == RESULT_SENT
    assert result.error is None
    assert result.to_dict().keys() == {"success", "status", "error", "timestamp"}


async def test_the_typed_message_actually_reaches_the_composer(driver, site):
    """Guards against 'clicked send on an empty box' — the worst failure mode,
    because the queue would record that as delivered.

    The stub POSTs whatever was in the composer at submit time, so this
    asserts on what the page really received, not on the driver's own
    verification.
    """
    message = "Hello alice, we loved your latest post — 90% of it anyway!"
    result = await driver.send_message(account(), target(site, "/alice"), message)

    assert result.success is True
    assert RECEIVED == [message]


async def test_nothing_is_submitted_when_the_composer_never_opens(driver, site):
    await driver.send_message(account(), target(site, "/redesigned"), "Hello there.")
    assert RECEIVED == []


async def test_a_send_that_silently_does_nothing_is_not_reported_as_sent(driver, site):
    """The regression that shipped: a real campaign reported "sent" with
    nothing delivered.

    The send button does nothing here, so the message is still sitting in
    the composer afterwards. The old check asked "is the message text
    anywhere on the page?", found its own leftover input, and called that
    success — which is how a campaign reports thousands sent having sent
    none.
    """
    result = await driver.send_message(
        account(), target(site, "/silentfail"), "Hello there, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_UNEXPECTED_PAGE
    assert "composer" in (result.error or "")


async def test_a_cleared_composer_alone_is_not_proof_of_delivery(driver, site):
    """Clearing the box is necessary but not sufficient — the message also
    has to show up in the conversation."""
    result = await driver.send_message(
        account(), target(site, "/swallowed"), "Hello there, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_UNEXPECTED_PAGE


async def test_delivery_that_cannot_be_confirmed_is_not_reported_as_sent(driver, site):
    result = await driver.send_message(
        account(), target(site, "/redesigned"), "Hello there."
    )
    assert result.success is False
    assert result.status == RESULT_UNEXPECTED_PAGE


# --- failure mapping -------------------------------------------------------

@pytest.mark.parametrize(
    "path,expected",
    [
        ("/nodm", RESULT_MESSAGING_UNAVAILABLE),
        ("/gone", RESULT_PROFILE_UNAVAILABLE),
        ("/loggedout", RESULT_SESSION_EXPIRED),
        ("/throttled", RESULT_RATE_LIMITED),
    ],
)
async def test_bad_page_states_map_to_statuses_not_exceptions(
    driver, site, path, expected
):
    result = await driver.send_message(account(), target(site, path), "Hi there.")
    assert result.success is False
    assert result.status == expected
    assert result.error


async def test_finds_a_message_control_built_as_a_div(driver, site):
    """The failure seen in production: the profile plainly had a Message
    button, but it is a div rather than a <button>, so the selectors missed
    it and the target was skipped as "does not accept DMs"."""
    message = "Hello alice, quick question."
    result = await driver.send_message(account(), target(site, "/divbutton"), message)
    assert result.success is True
    assert RECEIVED == [message]


async def test_a_nav_entry_cannot_win_over_the_real_button(driver, site):
    """The generic tier matches a nav "Messages" link just as well as the
    real control, and _first_visible races — so tier order is what stops the
    wrong element being clicked."""
    message = "Hello alice, quick question."
    result = await driver.send_message(account(), target(site, "/navdecoy"), message)
    assert result.success is True
    assert RECEIVED == [message]


async def test_the_nav_messages_link_cannot_win_over_a_late_rendering_button(
    driver, site
):
    """The production failure: `composer never opened`, with the log listing
    `inbox-title|…` entries — i.e. the driver was standing in the inbox.

    "Messages" in the left nav contains the word "Message", the loose tier
    matched it, and `_first_visible` races — so on a profile whose real
    control renders a beat late, the nav link wins, gets clicked, and
    navigates away from the profile entirely. Exact text matching is what
    stops it.
    """
    message = "Hello alice, quick question."
    result = await driver.send_message(account(), target(site, "/navmessages"), message)
    assert result.success is True
    assert RECEIVED == [message]


async def test_a_handoff_to_the_inbox_still_finds_the_targets_thread(driver, site):
    """Clicking Message does not always open a box in place — TikTok can
    navigate to its messages app, and the composer only exists once the
    conversation is selected."""
    message = "Hello alice, quick question."
    result = await driver.send_message(account(), target(site, "/inbox"), message)
    assert result.success is True
    # The thread it went to, not just that something was sent.
    assert RECEIVED == [f"alice|{message}"]


async def test_no_thread_for_the_target_never_messages_somebody_else(driver, site):
    """The inbox is full of other people's conversations. With no row for
    this target, the only safe move is to fail the job — DMing the closest
    match would send a stranger a message meant for someone else."""
    result = await driver.send_message(
        account(), target(site, "/inboxmiss"), "Hello alice, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_UNEXPECTED_PAGE
    assert RECEIVED == []
    # And it says which of the two composer failures this was.
    assert "inbox" in (result.error or "").lower()


async def test_a_consent_banner_over_the_button_does_not_lose_the_job(driver, site):
    """Seen in production as `Locator.click: Timeout 30000ms` on a button
    that was plainly visible: an overlay was intercepting the click. The
    driver should clear it and carry on rather than burning the attempt."""
    message = "Hello alice, quick question."
    result = await driver.send_message(account(), target(site, "/overlay"), message)
    assert result.success is True
    assert RECEIVED == [message]


async def test_a_missing_message_button_reports_what_the_page_does_offer(driver, site):
    """When a selector goes stale, "we didn't find it" is not a useful
    report — "here is what was there instead" is. Without this the only way
    to tell a renamed button from an account that blocks DMs is to drive a
    browser against the live site by hand."""
    result = await driver.send_message(
        account(), target(site, "/renamed"), "Hi there."
    )
    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE

    offered = result.detail.get("page_actions") or []
    assert "dm-entry|Chat" in offered
    assert "follow-button|Follow" in offered
    # And it must not claim to know which of the two causes it was.
    assert "either" in (result.error or "")


async def test_an_unreachable_host_is_a_result_not_a_crash(driver):
    result = await driver.send_message(
        {"id": 9, "name": "S", "platform": "tiktok", "session_state": "{}"},
        {"username": "x", "profile_url": "http://127.0.0.1:1/nope"},
        "Hi.",
    )
    assert result.success is False
    assert result.error


async def test_an_account_with_no_session_fails_before_opening_a_browser(driver, site):
    result = await driver.send_message(
        account(session=False), target(site, "/alice"), "Hi."
    )
    assert result.success is False
    assert result.status == RESULT_SESSION_EXPIRED
    assert 42 not in driver._contexts  # nothing was launched for it


# --- isolation and lifecycle ----------------------------------------------

async def test_each_account_gets_its_own_browser_context(driver, site):
    """The isolation guarantee: two accounts must never share cookies."""
    await driver.send_message(account(1, "Sender 1"), target(site, "/alice"), "Hi one.")
    await driver.send_message(account(2, "Sender 2"), target(site, "/bob", "bob"), "Hi two.")

    assert set(driver._contexts) == {1, 2}
    assert driver._contexts[1] is not driver._contexts[2]

    # Cookies set in one context are invisible in the other.
    await driver._contexts[1].add_cookies(
        [{"name": "sessionid", "value": "one", "url": site}]
    )
    assert [c["name"] for c in await driver._contexts[1].cookies(site)] == ["sessionid"]
    assert await driver._contexts[2].cookies(site) == []


async def test_the_context_survives_between_jobs(driver, site):
    """A job must not log the account out — the next job reuses the session."""
    await driver.send_message(account(), target(site, "/alice"), "First.")
    first = driver._contexts[1]
    await driver.send_message(account(), target(site, "/alice"), "Second.")
    assert driver._contexts[1] is first


async def test_pages_are_closed_after_every_job(driver, site):
    """Leaked pages are how a long-running worker ends up out of memory."""
    for _ in range(3):
        await driver.send_message(account(), target(site, "/alice"), "Hi.")
    assert driver._contexts[1].pages == []


async def test_release_account_drops_the_context(driver, site):
    await driver.send_message(account(), target(site, "/alice"), "Hi.")
    assert 1 in driver._contexts
    await driver.release_account(1)
    assert 1 not in driver._contexts
    # And releasing twice is harmless — the worker's finally block may double up.
    await driver.release_account(1)


async def test_export_session_returns_storage_state(driver, site):
    await driver.send_message(account(), target(site, "/alice"), "Hi.")
    exported = await driver.export_session({"id": 1})
    assert exported is not None
    assert "cookies" in json.loads(exported)
    assert await driver.export_session({"id": 999}) is None


# --- the verification puzzle ----------------------------------------------

async def test_a_puzzle_over_the_profile_is_not_blamed_on_the_target(driver, site):
    """The production failure, in its most expensive form.

    TikTok threw its slider puzzle over a perfectly ordinary profile. With
    no check for it the driver found no Message button, returned
    `messaging_unavailable` — which is *terminal* — and the queue skipped a
    real, reachable target for good. The account was never told to stop, so
    the next target got the same treatment.

    The target must survive this. Only the account is at fault.
    """
    result = await driver.send_message(
        account(), target(site, "/captchaonly"), "Hello alice, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_CHALLENGE_REQUIRED
    assert result.status not in TERMINAL_RESULTS, "a puzzle must never skip the target"
    assert RECEIVED == []


async def test_a_puzzle_covering_a_visible_button_is_reported_as_a_puzzle(driver, site):
    """Here the button *is* found — the overlay simply eats the click, so
    the composer never opens. That used to surface as `unexpected_page`,
    which is retryable but tells the operator nothing about what to do."""
    result = await driver.send_message(
        account(), target(site, "/captcha"), "Hello alice, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_CHALLENGE_REQUIRED
    assert RECEIVED == []


async def test_a_puzzle_inside_an_iframe_is_still_seen(driver, site):
    """How TikTok actually serves it. `page.locator` does not search into
    frames, so a selector-only check finds nothing and declares the page
    healthy — while the top document is empty enough to log the
    `page offers: []` that sent the last debugging round after the wrong
    bug entirely."""
    result = await driver.send_message(
        account(), target(site, "/captchaframe"), "Hello alice, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_CHALLENGE_REQUIRED
    assert RECEIVED == []


async def test_the_error_says_a_person_has_to_solve_it(driver, site):
    """The operator reads this string and needs to know it is their move —
    the driver deliberately cannot solve the puzzle itself."""
    result = await driver.send_message(
        account(), target(site, "/captchaonly"), "Hello alice, quick question."
    )
    assert "puzzle" in (result.error or "").lower()
    assert "target" in (result.error or "").lower()


async def test_a_puzzle_pauses_the_account_instead_of_burning_its_budget(driver, site):
    """Retrying cannot clear a challenge, and every attempt is another
    challenged request from an account TikTok already distrusts. So it
    pauses on the first one rather than after the error threshold."""
    assert RESULT_CHALLENGE_REQUIRED in ACCOUNT_FAULT_RESULTS
    assert RESULT_CHALLENGE_REQUIRED in IMMEDIATE_ACCOUNT_PAUSE_RESULTS


# --- diagnostics that do not lie -------------------------------------------

async def test_a_failed_action_dump_says_so_rather_than_looking_empty(driver, site):
    """`page offers: []` was read as "the page had nothing on it" when in
    truth the call had thrown and the page was never inspected. Two very
    different facts must not share one representation — the last debugging
    round was spent on the wrong bug because they did.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    await page.goto(f"{site}/alice")
    await page.close()

    actions = await PlaywrightTikTokMessenger._page_actions(page)
    assert actions, "a thrown diagnostic must not come back as an empty list"
    assert "failed" in actions[0]


async def test_waits_for_a_person_to_solve_the_puzzle_when_the_browser_is_visible(
    driver, site, monkeypatch
):
    """Detecting the puzzle instantly is right for a headless worker and
    wrong for `outreach-watch.sh`, which shows the browser over VNC for the
    express purpose of letting somebody clear it — bailing out closes the
    window in their face before they can touch it.

    Here the puzzle goes away after a beat, standing in for a solved slider.
    The send should then go through normally.
    """
    monkeypatch.setattr(
        "services.outreach.browser.playwright_tiktok.CHALLENGE_WAIT_MS", 15000
    )
    message = "Hello alice, quick question."
    result = await driver.send_message(account(), target(site, "/captchaclears"), message)

    assert result.success is True
    assert RECEIVED == [message]


async def test_a_headless_worker_does_not_sit_waiting_on_a_puzzle(driver, site):
    """Nobody is watching a background worker, so waiting would just hold a
    browser and the account's lease open for nothing. It fails immediately
    and lets the account pause."""
    result = await driver.send_message(
        account(), target(site, "/captchaclears"), "Hello alice, quick question."
    )
    assert result.success is False
    assert result.status == RESULT_CHALLENGE_REQUIRED
    assert RECEIVED == []


async def test_a_browser_closed_mid_job_is_not_blamed_on_the_target(driver, site):
    """The failure that cost a live target twice over.

    outreach-watch.sh stops the background workers on purpose, and the unit
    had no KillMode, so systemd SIGTERMed Chromium along with the worker. A
    closed page makes every selector helper return None — indistinguishable
    from a profile with no Message button — and that verdict is terminal, so
    the target was skipped permanently by the act of trying to watch it.

    Nothing is known about the target here, so nothing may be concluded.
    """
    async def close_the_page(page, *args, **kwargs):
        await page.close()
        return None

    driver._first_visible_tiered = close_the_page

    result = await driver.send_message(
        account(), target(site, "/alice"), "Hello alice, quick question."
    )
    assert result.status == RESULT_ABORTED
    assert result.status != RESULT_MESSAGING_UNAVAILABLE
    assert RECEIVED == []


async def test_an_aborted_job_neither_skips_the_target_nor_blames_the_account():
    """It has to stay retryable and blameless — the worker being restarted
    is nobody's fault and says nothing about either party."""
    assert RESULT_ABORTED not in TERMINAL_RESULTS
    assert RESULT_ABORTED not in ACCOUNT_FAULT_RESULTS


async def test_a_puzzle_that_swallowed_the_click_gets_the_click_again(
    driver, site, monkeypatch
):
    """Seen twice against live TikTok, and it wasted a solved puzzle both
    times:

        message-button: needed a force click
        verification puzzle — waiting up to 300s
        puzzle cleared — carrying on
        composer never opened

    The challenge consumed the click. Clearing it does not replay that
    click, so the driver sat waiting for a composer nothing had asked for,
    then blamed the page — while the screenshot showed a healthy profile
    with its Message button untouched. Waiting for the puzzle is only half
    the fix; the click has to be made again.
    """
    monkeypatch.setattr(
        "services.outreach.browser.playwright_tiktok.CHALLENGE_WAIT_MS", 15000
    )
    message = "Hello alice, quick question."
    result = await driver.send_message(
        account(), target(site, "/captchaeatsclick"), message
    )

    assert result.success is True, result.error
    assert RECEIVED == [message]
