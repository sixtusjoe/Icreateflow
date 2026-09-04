"""Server-side session capture (`scripts/outreach_login.py`).

Drives the real capture flow against a stub "login page" that sets the
session cookie on a timer, standing in for a person typing a password.
Verifies the part that matters operationally: a completed sign-in lands in
the account row encrypted, and an abandoned one changes nothing.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api", reason="playwright is not installed")

import database as db  # noqa: E402
from services.outreach.crypto import decrypt_session  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "outreach_login",
    Path(__file__).resolve().parent.parent / "scripts" / "outreach_login.py",
)
outreach_login = importlib.util.module_from_spec(_SPEC)
sys.modules["outreach_login"] = outreach_login
_SPEC.loader.exec_module(outreach_login)


#: Sets the session cookie after a beat — what a human logging in looks like
#: to the poll loop.
LOGIN_THEN_SUCCEED = """
<html><body>
  <h1>Sign in</h1>
  <script>
    setTimeout(function () {
      document.cookie = 'sessionid=stub-session-value; path=/';
    }, 800);
  </script>
</body></html>
"""

#: Never signs in — the operator wandered off.
LOGIN_NEVER_COMPLETES = "<html><body><h1>Sign in</h1></body></html>"

PAGES = {"/ok": LOGIN_THEN_SUCCEED, "/never": LOGIN_NEVER_COMPLETES}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGES.get(self.path, "<html><body>?</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


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
def headless(monkeypatch):
    # The real script opens a visible window on the server's X display;
    # there is none here.
    monkeypatch.setenv("ICREATE_LOGIN_HEADLESS", "1")


def _point_at(monkeypatch, url: str) -> None:
    monkeypatch.setattr(
        outreach_login,
        "PLATFORMS",
        {"tiktok": {"login_url": url, "cookie": "sessionid", "domain": "127.0.0.1"}},
    )


async def test_a_completed_sign_in_is_encrypted_into_the_account(
    database, account_factory, site, monkeypatch
):
    account = await account_factory(name="Sender 1", with_session=False)
    _point_at(monkeypatch, f"{site}/ok")

    try:
        code = await outreach_login.capture(account["id"], timeout_seconds=30)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium is not available: {exc}")

    assert code == 0

    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["session_state_encrypted"]
    assert row["session_updated_at"] is not None
    assert row["status"] == "idle"
    assert row["session_reference"] == f"server-login/account-{account['id']}"

    # It is genuinely the captured session, and genuinely encrypted.
    assert "stub-session-value" not in row["session_state_encrypted"]
    state = json.loads(decrypt_session(row["session_state_encrypted"]))
    assert any(
        c["name"] == "sessionid" and c["value"] == "stub-session-value"
        for c in state["cookies"]
    )


async def test_an_abandoned_sign_in_changes_nothing(
    database, account_factory, site, monkeypatch
):
    account = await account_factory(name="Sender 2", with_session=False)
    _point_at(monkeypatch, f"{site}/never")

    try:
        code = await outreach_login.capture(account["id"], timeout_seconds=6)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium is not available: {exc}")

    assert code == 1
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["session_state_encrypted"] is None
    assert row["session_updated_at"] is None


async def test_an_unknown_account_is_reported_not_crashed(database, monkeypatch, site):
    _point_at(monkeypatch, f"{site}/ok")
    assert await outreach_login.capture(999_999, timeout_seconds=5) == 1


async def test_an_unsupported_platform_is_reported(
    database, account_factory, monkeypatch, site
):
    account = await account_factory(name="IG", with_session=False)
    await db.update_sending_account(database, account["id"], platform="instagram")
    _point_at(monkeypatch, f"{site}/ok")
    assert await outreach_login.capture(account["id"], timeout_seconds=5) == 1
