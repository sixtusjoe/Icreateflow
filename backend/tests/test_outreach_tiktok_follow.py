"""TikTok's phantom follow: accepted, acknowledged, and not kept.

Measured 2026-09-23 against the live site on two accounts, three attempts:
`POST /api/commit/follow/user/` answered HTTP 200 with
`{"status_code": 0, "follow_status": 1, "status_msg": ""}` and the button
turned to "Following" — and a reload showed "Follow" again every time.

That is the worst shape a failure can take. Every signal the driver had
said success, so a follow campaign would have reported a thousand sends
and followed nobody, exactly as Instagram's phantom confirmations once
did. The only thing that tells the truth is loading the profile again.

The server below is that behaviour in miniature: `/phantom` flips its
button in the page and forgets it, `/honest` actually remembers.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.outreach.browser.playwright_tiktok import PlaywrightTikTokMessenger
from services.outreach.constants import RESULT_FOLLOW_DISCARDED, RESULT_SENT

pytestmark = pytest.mark.asyncio

#: Whether `/honest` has been followed. `/phantom` never records anything.
STATE: dict[str, bool] = {"honest_followed": False}

#: A button that turns itself into "Following" on click and tells the
#: server nothing — which is precisely what TikTok's page does once the
#: server has decided to drop the follow on the floor.
_PAGE = """<html><body>
  <h1>@someone</h1>
  <button data-e2e="follow-button"
          style="width:120px;height:40px"
          onclick="this.textContent='Following'; {extra}">{label}</button>
  <div style="margin-top:600px">
    <button data-e2e="follow-button" style="width:120px;height:40px">Follow</button>
  </div>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/record"):
            STATE["honest_followed"] = True
            self._send(204, "")
            return
        if self.path == "/honest":
            label = "Following" if STATE["honest_followed"] else "Follow"
            body = _PAGE.format(label=label, extra="fetch('/record');")
        else:
            # The phantom: the click changes the page and nothing else, so
            # the next load serves "Follow" again.
            body = _PAGE.format(label="Follow", extra="")
        self._send(200, body)

    def _send(self, code: int, body: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(body.encode())

    def log_message(self, *_args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    STATE["honest_followed"] = False
    monkeypatch.setattr("services.outreach.browser.playwright_base.DEBUG_DIR", "")
    monkeypatch.setattr(
        "services.outreach.browser.playwright_base.FOLLOW_CONTROL_POLLS", 12)
    monkeypatch.setattr(
        "services.outreach.browser.playwright_base.FOLLOW_CONFIRM_POLLS", 6)


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


def account() -> dict:
    return {
        "id": 1, "name": "Sender", "platform": "tiktok",
        "session_state": json.dumps({"cookies": [], "origins": []}),
    }


async def test_a_follow_the_platform_throws_away_is_not_a_send(driver, site):
    """The button said Following. The reload said otherwise, and it wins."""
    result = await driver.follow_target(
        account(), {"username": "someone", "profile_url": f"{site}/phantom"})

    assert result.status == RESULT_FOLLOW_DISCARDED, (
        f"a discarded follow was reported as {result.status!r} — this is the "
        f"failure that looks exactly like success"
    )
    assert not result.success
    assert "discarded" in (result.error or "").lower()


async def test_a_follow_that_sticks_is_still_a_send(driver, site):
    """The check must not call a real follow a phantom.

    Without this the safe move is to fail every follow, which would read as
    "we fixed it" right up until nobody could follow anyone.
    """
    result = await driver.follow_target(
        account(), {"username": "someone", "profile_url": f"{site}/honest"})

    assert result.status == RESULT_SENT, f"a real follow was rejected: {result.error}"
    assert result.success
