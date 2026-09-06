"""The Instagram driver, against a local stub — never instagram.com.

What this proves: that Instagram's selector table drives the shared engine
correctly. The profile is found, the Message control is picked out without
the navigation stealing the click, the composer is typed into, delivery is
confirmed the hard way, and each bad page maps to the right status.

What it cannot prove is that these selectors still match the real site —
only a run against instagram.com does that, and none has happened yet. The
selectors are a hypothesis; the engine underneath them is not.

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

from services.outreach.browser.playwright_instagram import (  # noqa: E402
    PlaywrightInstagramMessenger,
)
from services.outreach.constants import (  # noqa: E402
    RESULT_MESSAGE_REFUSED,
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_SENT,
    RESULT_SESSION_EXPIRED,
    TERMINAL_RESULTS,
)

# --- stub pages, using the hooks the Instagram table looks for -------------

_COMPOSER = """
  <div id="chat" style="display:none">
    <div role="textbox" contenteditable="true"></div>
    <div role="button" onclick="sendChat()">Send</div>
    <div id="thread"></div>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function sendChat() {
      const ed = document.querySelector('div[role="textbox"]');
      const row = document.createElement('div');
      row.setAttribute('role', 'row');
      row.textContent = ed.innerText;
      document.getElementById('thread').appendChild(row);
      fetch('/sent', { method: 'POST', body: ed.innerText });
      ed.innerText = '';
    }
  </script>
"""

SENDABLE = f"""
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button" onclick="openChat()">Message</div>
  {_COMPOSER}
</body></html>
"""

#: Instagram's left navigation has a "Messages" entry, exactly like TikTok's.
#: It is a link, and the profile's own control renders a beat later.
NAV_MESSAGES_DECOY = f"""
<html><body>
  <nav><a href="/direct/inbox/">Messages</a></nav>
  <header><section><h2>alice</h2></section></header>
  <div id="late"></div>
  {_COMPOSER}
  <script>
    setTimeout(function () {{
      const b = document.createElement('div');
      b.setAttribute('role', 'button');
      b.textContent = 'Message';
      b.onclick = openChat;
      document.getElementById('late').appendChild(b);
    }}, 600);
  </script>
</body></html>
"""

NO_MESSAGE_BUTTON = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button">Follow</div>
</body></html>
"""

MISSING_PROFILE = "<html><body><p>Sorry, this page isn't available.</p></body></html>"

LOGIN_WALL = """
<html><body>
  <h2>Log in to Instagram</h2>
  <input name="username" />
</body></html>
"""

SEND_REFUSED = f"""
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button" onclick="openChat()">Message</div>
  {_COMPOSER.replace("fetch('/sent'", "document.getElementById('notice').style.display='block'; fetch('/sent'")}
  <div id="notice" style="display:none">Message failed to send</div>
</body></html>
"""

PAGES = {
    "/alice": SENDABLE,
    "/navdecoy": NAV_MESSAGES_DECOY,
    "/nodm": NO_MESSAGE_BUTTON,
    "/gone": MISSING_PROFILE,
    "/loggedout": LOGIN_WALL,
    "/refused": SEND_REFUSED,
}

RECEIVED: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's interface
        body = PAGES.get(self.path, "<html><body>not found</body></html>")
        # Serve back what was submitted. The engine confirms a send by
        # reloading, so a stub that stores nothing would fail every send.
        if '<div id="thread"></div>' in body:
            rows = "".join(f'<div role="row">{m}</div>' for m in RECEIVED)
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
        ("COMPOSER_MS", 2000), ("SETTLE_MS", 300),
    ):
        monkeypatch.setattr(f"services.outreach.browser.playwright_base.{name}", value)


@pytest.fixture
async def driver():
    messenger = PlaywrightInstagramMessenger(headless=True, timeout_ms=8000)
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
        "platform": "instagram",
        "session_state": json.dumps({"cookies": [], "origins": []}),
    }


def target(site: str, path: str, username: str = "alice") -> dict:
    return {"username": username, "profile_url": f"{site}{path}"}


# --- the shared engine, driven by Instagram's table ------------------------

async def test_sends_and_confirms_delivery(driver, site):
    message = "Hi alice, loved the last post."
    result = await driver.send_message(account(), target(site, "/alice"), message)

    assert result.success is True, result.error
    assert result.status == RESULT_SENT
    # What the page actually received, not what the driver believed.
    assert RECEIVED == [message]


async def test_the_navigation_messages_link_cannot_win(driver, site):
    """Instagram's nav has a "Messages" entry and the profile's own control
    renders late. This is the bug that cost a live target on TikTok, so the
    generic tier here is exact-text and never matches a link."""
    message = "Hi alice, quick question."
    result = await driver.send_message(account(), target(site, "/navdecoy"), message)
    assert result.success is True, result.error
    assert RECEIVED == [message]


async def test_a_profile_without_a_message_control_is_not_permanent(driver, site):
    """No Message button is inferred from an absence, and absence has too
    many innocent causes to write a target off for good."""
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
    result = await driver.send_message(account(), target(site, "/loggedout"), "Hi alice.")
    assert result.success is False
    assert result.status == RESULT_SESSION_EXPIRED


async def test_a_refused_message_is_not_reported_as_sent(driver, site):
    """Instagram refuses messages too, and says so in its own words. The
    engine's rule is unchanged: anything the platform declines is not a
    send, whatever the composer did."""
    result = await driver.send_message(account(), target(site, "/refused"), "Hi alice.")
    assert result.success is False
    assert result.status == RESULT_MESSAGE_REFUSED
