"""Open an account's saved session, signed in, and save it back on close.

Re-login only ever showed a sign-in page, so a verification puzzle met by
a message campaign could not be cleared as the account (2026-09-29).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright.async_api", reason="playwright is not installed")

import database as db  # noqa: E402
from services.outreach import session_capture  # noqa: E402
from services.outreach.crypto import decrypt_session, encrypt_session  # noqa: E402

#: The inbox, where the puzzle was: solving it leaves a cookie behind.
SOLVED = """<html><body><h1>Messages</h1><script>
  document.cookie = 'puzzle=solved; path=/';
</script></body></html>"""
#: An inbox that signs the account out.
SIGNS_OUT = """<html><body><script>
  document.cookie = 'sessionid=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = {"/inbox": SOLVED, "/signsout": SIGNS_OUT}.get(self.path, "<html></html>")
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
    monkeypatch.setenv("ICREATE_LOGIN_HEADLESS", "1")


def _point_at(monkeypatch, url: str) -> None:
    monkeypatch.setattr(session_capture, "PLATFORMS",
                        {"tiktok": {"login_url": url, "cookie": "sessionid", "domain": "127.0.0.1"}})
    monkeypatch.setattr(session_capture, "OPEN_URLS", {"tiktok": url})


async def _signed_in(database, account_factory) -> dict:
    account = await account_factory(name="RealMic TikTok", with_session=False)
    state = {"cookies": [{"name": "sessionid", "value": "saved-session", "domain": "127.0.0.1",
                          "path": "/", "expires": -1, "httpOnly": False, "secure": False,
                          "sameSite": "Lax"}], "origins": []}
    await db.update_sending_account(database, account["id"],
                                    session_state_encrypted=encrypt_session(json.dumps(state)))
    return dict(await db.get_sending_account(database, account["id"]))


async def _run(account: dict) -> session_capture.Capture:
    capture = session_capture.start(account, timeout_seconds=4, reuse=True)
    try:
        await session_capture._TASKS[int(account["id"])]
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium is not available: {exc}")
    return capture


async def test_the_saved_session_opens_signed_in_and_is_saved_back(
        database, account_factory, site, monkeypatch):
    _point_at(monkeypatch, f"{site}/inbox")
    account = await _signed_in(database, account_factory)
    capture = await _run(account)

    assert capture.status == session_capture.STATUS_SAVED, capture.message
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["session_reference"] == f"browser-open/account-{account['id']}"
    cookies = {c["name"]: c["value"] for c in json.loads(
        decrypt_session(row["session_state_encrypted"]))["cookies"]}
    assert cookies["sessionid"] == "saved-session"  # it opened signed in, as the account
    assert cookies["puzzle"] == "solved"  # and what the window did is kept


async def test_a_window_that_ends_signed_out_saves_nothing(
        database, account_factory, site, monkeypatch):
    _point_at(monkeypatch, f"{site}/signsout")
    account = await _signed_in(database, account_factory)
    before = account["session_state_encrypted"]
    capture = await _run(account)

    assert capture.status == session_capture.STATUS_FAILED
    assert "signed out" in capture.message
    row = dict(await db.get_sending_account(database, account["id"]))
    assert row["session_state_encrypted"] == before


async def test_an_account_with_no_saved_session_is_told_to_sign_in(
        database, account_factory):
    account = await account_factory(name="Fresh", with_session=False)
    with pytest.raises(ValueError, match="no saved session"):
        session_capture.start(dict(await db.get_sending_account(database, account["id"])),
                              reuse=True)
