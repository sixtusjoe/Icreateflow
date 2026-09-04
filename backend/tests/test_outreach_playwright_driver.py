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
    RESULT_MESSAGING_UNAVAILABLE,
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_RATE_LIMITED,
    RESULT_SENT,
    RESULT_SESSION_EXPIRED,
    RESULT_UNEXPECTED_PAGE,
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

PAGES = {
    "/alice": SENDABLE,
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
def clear_received():
    RECEIVED.clear()


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
