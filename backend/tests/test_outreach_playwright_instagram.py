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
    ACCOUNT_FAULT_RESULTS,
    RESULT_ALREADY_FOLLOWING,
    RESULT_FOLLOW_REQUESTED,
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
  <button type="button"><div class="_ap3a">Follow</div></button>
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

#: What Instagram actually did. The send happens in a chat dock over the
#: profile, so a reload comes back to a bare profile with no conversation on
#: it — a delivered message and a discarded one look identical. Reopening
#: the conversation asks the server, and the message is there.
DOCK_OVER_PROFILE = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button" onclick="openChat()">Message</div>
  <div id="chat" style="display:none">
    <div role="textbox" contenteditable="true"></div>
    <div role="button" onclick="sendChat()">Send</div>
    <div id="thread"></div>
  </div>
  <script>
    // The dock is closed on load, exactly as a reloaded profile is. The
    // thread only exists once the conversation is opened.
    function openChat() {
      document.getElementById('chat').style.display = 'block';
      fetch('/history').then(r => r.text()).then(html => {
        document.getElementById('thread').innerHTML = html;
      });
    }
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
</body></html>
"""

#: A composer that takes an image, the way Instagram's does — a hidden file
#: input behind the photo icon. Clicking the icon would open an OS picker no
#: automation can reach; setting the input is the only route in.
WITH_ATTACHMENT = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button" onclick="openChat()">Message</div>
  <div id="chat" style="display:none">
    <div role="textbox" contenteditable="true"></div>
    <input type="file" accept="image/*" style="display:none" onchange="picked()" />
    <div role="button" onclick="sendChat()">Send</div>
    <div id="thread"></div>
  </div>
  <script>
    let attached = '';
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function picked() {
      const f = document.querySelector('input[type=file]').files[0];
      attached = f ? f.name : '';
    }
    function sendChat() {
      const ed = document.querySelector('div[role="textbox"]');
      const row = document.createElement('div');
      row.setAttribute('role', 'row');
      // The stub reports the attachment alongside the text, so a test can
      // assert the image really reached the composer.
      row.textContent = ed.innerText;
      document.getElementById('thread').appendChild(row);
      fetch('/sent', { method: 'POST', body: ed.innerText + '|img=' + attached });
      ed.innerText = '';
    }
  </script>
</body></html>
"""

#: A composer where Enter sends, which is what every chat box on the web
#: does and what the earlier stubs did not. Typing a template with a line
#: break in it into this page submits the first line on its own.
ENTER_SENDS = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button" onclick="openChat()">Message</div>
  <div id="chat" style="display:none">
    <div role="textbox" contenteditable="true"></div>
    <div role="button" onclick="sendChat()">Send</div>
    <div id="thread"></div>
  </div>
  <script>
    function openChat() { document.getElementById('chat').style.display = 'block'; }
    function sendChat() {
      const ed = document.querySelector('div[role="textbox"]');
      const text = ed.innerText;
      if (!text.trim()) return;
      const row = document.createElement('div');
      row.setAttribute('role', 'row');
      row.innerText = text;
      document.getElementById('thread').appendChild(row);
      fetch('/sent', { method: 'POST', body: text });
      ed.innerHTML = '';
    }
    document.addEventListener('keydown', function (e) {
      if (e.target.getAttribute('role') !== 'textbox') return;
      // Enter sends. Shift+Enter is left alone, so the browser inserts the
      // line break itself — exactly the distinction the composer relies on.
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
  </script>
</body></html>
"""

#: What Instagram does when the recipient does not take requests: it renders
#: the message in the thread exactly like a delivered one, and puts the
#: refusal in among the bubbles. `nolove_lu` looked identical to three
#: genuine deliveries in the same run — same blue bubbles, same timestamp —
#: with one grey line of text between them saying it had not gone anywhere.
REQUEST_REFUSED = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div role="button" onclick="openChat()">Message</div>
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
      row.innerText = ed.innerText;
      const thread = document.getElementById('thread');
      thread.appendChild(row);
      const notice = document.createElement('div');
      notice.textContent = "This account can't receive your message because "
        + "they don't allow new message requests from everyone.";
      thread.appendChild(notice);
      ed.innerHTML = '';
    }
  </script>
</body></html>
"""

#: Not private, but only takes messages from people it follows. The Message
#: button is genuinely absent until the follow lands, and then it appears in
#: place — no reload, no navigation.
FOLLOW_UNLOCKS_MESSAGE = f"""
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="follow()"><div class="_ap3a">Follow</div></button>
  </div>
  {_COMPOSER}
  <script>
    function follow() {{
      document.getElementById('actions').innerHTML =
        '<button type="button"><div class="_ap3a">Following</div></button>'
        + '<div role="button" onclick="openChat()">Message</div>';
    }}
  </script>
</body></html>
"""

#: Instagram's button as it really is after a follow, measured 2026-09-24:
#: it *shows* "Following", but a dropdown chevron inside it carries an SVG
#: <title>, so its textContent is "FollowingDown chevron icon". A driver
#: matching textContent exactly never saw the follow land, called it a
#: follow limit, and paused the campaign for six hours after every follow.
_CHEVRON = ('<svg aria-label="Down chevron icon" width="12" height="12">'
            '<title>Down chevron icon</title><path d="M0 0h12v12H0z"/></svg>')
FOLLOW_CHEVRON = f"""
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="follow()"><div class="_ap3a">Follow</div></button>
  </div>
  <div style="margin-top:400px">
    <p>Suggested for you</p>
    <button type="button"><div>Follow</div></button>
    <button type="button"><div>Follow</div></button>
  </div>
  <script>
    function follow() {{
      document.getElementById('actions').innerHTML =
        '<button type="button" onclick="fetch(\\'/sent\\', {{method: \\'POST\\', body: \\'UNFOLLOWED\\'}})">'
        + '<div class="_ap3a">Following</div>{_CHEVRON}</button>';
    }}
  </script>
</body></html>
"""

#: Already followed, in the same real markup. Both pages carry the
#: "Suggested for you" row: with the profile's own button unreadable, the
#: topmost exact "Follow" on the page is a stranger's, and that is what
#: the driver read as the profile still saying Follow.
ALREADY_FOLLOWING_CHEVRON = f"""
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="fetch('/sent', {{ method: 'POST', body: 'UNFOLLOWED' }})">
      <div class="_ap3a">Following</div>{_CHEVRON}
    </button>
  </div>
  <div style="margin-top:400px">
    <p>Suggested for you</p>
    <button type="button"><div>Follow</div></button>
    <button type="button"><div>Follow</div></button>
  </div>
</body></html>
"""

#: The follow lands on the server, but the page is slow to say so: the
#: button has not changed by the time the driver stops watching it. Only a
#: reload shows "Following". Measured 2026-09-24: @byisci was reported as a
#: follow limit — and paused the campaign six hours — while followed.
SLOW_FOLLOW = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="fetch('/sent', {method: 'POST', body: 'SLOWFOLLOWED'})">
      <div>Follow</div></button>
  </div>
  <div style="margin-top:400px"><button type="button"><div>Follow</div></button></div>
</body></html>
"""
SLOW_FOLLOWED = f"""
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions"><button type="button"><div>Following</div>{_CHEVRON}</button></div>
  <div style="margin-top:400px"><button type="button"><div>Follow</div></button></div>
</body></html>
"""

#: A real limit: the press is ignored, and a reload still says Follow.
IGNORED_FOLLOW = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions"><button type="button"><div>Follow</div></button></div>
</body></html>
"""

#: Unfollowing, as Instagram does it (measured 2026-09-24): Following opens
#: a menu — Add to close friends list, Add to favorites, Mute, Restrict,
#: Unfollow. `/unfollowme` remembers the unfollow; `/unfollowlies` flips its
#: button and forgets, so only a reload tells the truth.
_SUGGESTED = """<div style="margin-top:400px"><p>Suggested for you</p>
  <button type="button" onclick="fetch('/sent',{method:'POST',body:'FOLLOWED-STRANGER'})"><div>Follow</div></button></div>"""
_MENU = """<div role="dialog">
  <button>Add to close friends list</button><button>Add to favorites</button>
  <button>Mute</button><button>Restrict</button>
  <button onclick="{action}">Unfollow</button></div>"""
def _unfollow_page(record: bool, after: str = "Follow") -> str:
    action = ("fetch('/sent',{method:'POST',body:'UNFOLLOWED'});" if record else "") + \
        f"document.getElementById('actions').innerHTML='<button type=button><div>{after}</div></button>';" \
        "document.getElementById('menu').innerHTML='';"
    return f"""<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions"><button type="button"
      onclick="document.getElementById('menu').innerHTML = document.getElementById('tpl').innerHTML">
    <div>Following</div>{_CHEVRON}</button></div>
  <div id="menu"></div>
  <template id="tpl">{_MENU.format(action=action.replace('"', '&quot;'))}</template>
  {_SUGGESTED}
</body></html>"""
#: They follow this account and it doesn't follow them: "Follow Back",
#: with the suggestions' plain "Follow" buttons further down.
FOLLOWS_BACK_PAGE = f"""<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions"><button type="button" onclick="fetch('/sent',{{method:'POST',body:'FOLLOWED'}})"><div>Follow Back</div></button></div>
  {_SUGGESTED}
</body></html>"""
UNFOLLOWED_PAGE = f"""<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions"><button type="button" onclick="fetch('/sent',{{method:'POST',body:'FOLLOWED'}})"><div>Follow</div></button></div>
  {_SUGGESTED}
</body></html>"""

#: Private. Follow turns into "Requested" and the profile stays shut — the
#: request has to be accepted by a person before anything can be sent.
PRIVATE_ACCOUNT = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="request()"><div class="_ap3a">Follow</div></button>
  </div>
  <script>
    function request() {
      document.getElementById('actions').innerHTML =
        '<button type="button"><div class="_ap3a">Requested</div></button>';
    }
  </script>
</body></html>
"""

#: Already followed, and still no Message button. Following is not what is
#: in the way — and the control now says "Following", so clicking it would
#: unfollow someone the operator meant to keep.
ALREADY_FOLLOWING = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="fetch('/sent', { method: 'POST', body: 'UNFOLLOWED' })">
      <div class="_ap3a">Following</div>
    </button>
  </div>
</body></html>
"""


#: A profile with a Follow button of its own, and — below it — Instagram's
#: "Suggested for you" row, whose entries carry *their own* Follow and
#: Following buttons built from the same markup.
#:
#: This is the Instagram version of the trap X's `_profile_follow_control`
#: override exists for. The selector table is matched page-wide
#: (`page.locator(sel).first`), so a "Following" button belonging to a
#: suggestion can answer a question that was asked about the profile:
#: before pressing it reads as "already followed" and the real follow is
#: skipped; after pressing it confirms a follow that never landed. Either
#: way the job is recorded as done and the account's following count does
#: not move — which is what 72 sends and 36 follows looks like.
SUGGESTIONS_BELOW = """
<html><body>
  <header><section><h2>alice</h2></section></header>
  <div id="actions">
    <button type="button" onclick="follow()"><div class="_ap3a">Follow</div></button>
  </div>
  <div id="suggested">
    <h3>Suggested for you</h3>
    <button type="button"><div class="_ap3a">Following</div></button>
    <button type="button"><div class="_ap3a">Following</div></button>
    <button type="button"><div class="_ap3a">Follow</div></button>
  </div>
  <script>
    function follow() {
      document.getElementById('actions').innerHTML =
        '<button type="button"><div class="_ap3a">Following</div></button>';
      fetch('/sent', { method: 'POST', body: 'FOLLOWED-ALICE' });
    }
  </script>
</body></html>
"""

PAGES = {
    "/alice": SENDABLE,
    "/entersends": ENTER_SENDS,
    "/requestrefused": REQUEST_REFUSED,
    "/withimage": WITH_ATTACHMENT,
    "/dock": DOCK_OVER_PROFILE,
    "/navdecoy": NAV_MESSAGES_DECOY,
    "/nodm": NO_MESSAGE_BUTTON,
    "/followunlocks": FOLLOW_UNLOCKS_MESSAGE,
    "/private": PRIVATE_ACCOUNT,
    "/following": ALREADY_FOLLOWING,
    "/followchevron": FOLLOW_CHEVRON,
    "/slowfollow": SLOW_FOLLOW,
    "/ignoredfollow": IGNORED_FOLLOW,
    "/followingchevron": ALREADY_FOLLOWING_CHEVRON,
    "/suggestions": SUGGESTIONS_BELOW,
    "/gone": MISSING_PROFILE,
    "/loggedout": LOGIN_WALL,
    "/refused": SEND_REFUSED,
}

RECEIVED: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's interface
        if self.path == "/history":
            # What the server has actually stored for this conversation.
            body = "".join(f'<div role="row">{m}</div>' for m in RECEIVED)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
            return
        body = PAGES.get(self.path, "<html><body>not found</body></html>")
        if self.path == "/slowfollow" and "SLOWFOLLOWED" in RECEIVED:
            body = SLOW_FOLLOWED
        if self.path == "/unfollowme":
            body = UNFOLLOWED_PAGE if "UNFOLLOWED" in RECEIVED else _unfollow_page(True)
        if self.path == "/unfollowlies":
            body = _unfollow_page(False)
        if self.path == "/unfollowback":
            body = FOLLOWS_BACK_PAGE if "UNFOLLOWED" in RECEIVED else _unfollow_page(True, "Follow Back")
        if self.path == "/followsback":
            body = FOLLOWS_BACK_PAGE
        if self.path == "/notfollowed":
            body = UNFOLLOWED_PAGE
        # Serve back what was submitted. The engine confirms a send by
        # reloading, so a stub that stores nothing would fail every send.
        # `/dock` is the exception: its conversation does not exist until it
        # is opened, which is the whole point of that page. Pre-filling it
        # would hide the bug it exists to reproduce.
        if self.path not in ("/dock", "/requestrefused") and '<div id="thread"></div>' in body:
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


def target(
    site: str, path: str, username: str = "alice", follow_to_unlock: bool = True
) -> dict:
    return {
        "username": username,
        "profile_url": f"{site}{path}",
        "follow_to_unlock": follow_to_unlock,
    }


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


async def test_a_send_from_a_dock_over_the_profile_is_confirmed(driver, site):
    """The first real Instagram send, and the driver called it undelivered.

    The message arrived — it was sitting in the recipient's requests — but
    Instagram sends from a chat dock over the profile, so reloading came
    back to a bare profile with no conversation on it. Nothing to find, so
    the delivery check reported nothing delivered, left the target queued,
    and would have messaged the same person twice on the retry.

    Reopening the conversation asks the platform for it, which is the same
    proof the reload was after: a message that comes back was really stored.
    """
    message = "Hi alice, quick question."
    result = await driver.send_message(account(), target(site, "/dock"), message)

    assert result.success is True, result.error
    assert RECEIVED == [message]


async def test_an_image_reaches_the_composer_before_the_message_is_sent(
    driver, site, tmp_path
):
    """The image has to be in the composer when it submits, not after.

    Added afterwards it would be a second, separate message — which is not
    what "send this image with this text" means.
    """
    image = tmp_path / "promo.png"
    # A one-pixel PNG: enough for a file input to accept.
    image.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    ))
    message = "Hi alice, quick question."
    t = target(site, "/withimage")
    t["attachment_path"] = str(image)

    result = await driver.send_message(account(), t, message)

    assert result.success is True, result.error
    assert RECEIVED == [f"{message}|img=promo.png"]


async def test_a_platform_that_cannot_send_images_says_so_and_sends_nothing(
    driver, site, tmp_path
):
    """TikTok's web composer is text only. Sending the text alone and
    reporting success would be the same class of lie as claiming a delivery
    that never happened — so it fails, and says which thing to change."""
    from services.outreach.browser.playwright_tiktok import PlaywrightTikTokMessenger

    image = tmp_path / "promo.png"
    image.write_bytes(b"not really a png, never opened")

    text_only = PlaywrightTikTokMessenger(headless=True, timeout_ms=8000)
    assert not text_only.SELECTORS.get("attach_image"), (
        "this test is meaningless if TikTok grows an attachment control"
    )
    problem = await text_only._attach_image(None, str(image), "alice")
    assert problem and "cannot carry an image" in problem


async def test_a_missing_image_file_is_reported_rather_than_skipped(driver, tmp_path):
    """An attachment the campaign points at but which is not on disk is a
    real problem, not something to quietly send without."""
    problem = await driver._attach_image(None, str(tmp_path / "gone.png"), "alice")
    assert problem and "missing from disk" in problem


async def test_a_line_break_in_the_template_stays_inside_one_message(driver, site):
    """A two-line template was arriving as two separate messages.

    Typing the text typed its newline as Enter, and Enter in a chat composer
    sends. So "We ship to USA only! ... / ask us how to get a free sample!"
    left as two bubbles, and the delivery check — looking for the whole
    string in one place — found neither and called a real send a failure.

    Shift+Enter is the line break these composers accept.
    """
    message = "We ship to USA only! t.me/wesellmuha\nask us how to get a free sample!"

    result = await driver.send_message(account(), target(site, "/entersends"), message)

    assert result.success is True, result.error
    assert RECEIVED == [message], (
        f"expected one message with a line break in it, got {RECEIVED!r}"
    )


async def test_a_refusal_among_the_bubbles_is_not_a_delivery(driver, site):
    """The message can be in the thread and still have gone nowhere.

    Four targets in one run reported the same failure, and the screenshots
    showed three of them genuinely delivered. The fourth had the identical
    blue bubbles and, between them, one grey line: the account does not
    accept message requests. Nothing about the thread distinguished it.

    So the thread is not the evidence — it never was. This is why a send is
    confirmed by asking the platform again rather than by reading back what
    the client drew.
    """
    result = await driver.send_message(
        account(), target(site, "/requestrefused"), "Hi alice, quick question."
    )

    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE, result.error
    # And specifically not a refusal: that bucket counts against the sending
    # account and pauses it. A stranger with a closed inbox is not evidence
    # of anything being wrong with the account doing the sending.
    assert result.status not in ACCOUNT_FAULT_RESULTS


# --- following to unlock the Message button --------------------------------

async def test_following_reveals_the_message_button_and_the_send_continues(
    driver, site
):
    """An account with no Message button is not necessarily unreachable.

    Plenty of profiles are public but only accept messages from people they
    follow, and on those the button appears once the follow lands. Two were
    confirmed reachable this way by hand, after the run had already written
    them off as not accepting DMs.

    The message goes out on the same visit — there is no reason to come back
    for it once the button is there.
    """
    message = "Hi alice, quick question."

    result = await driver.send_message(
        account(), target(site, "/followunlocks"), message
    )

    assert result.success is True, result.error
    assert result.status == RESULT_SENT
    assert RECEIVED == [message]


async def test_a_private_account_is_requested_and_left_alone(driver, site):
    """Follow becomes "Requested" and nothing else happens.

    A private account cannot be messaged until a person accepts, so there is
    nothing to wait for on this visit and nothing to retry quickly. What
    matters is that it is not reported as a send.
    """
    result = await driver.send_message(
        account(), target(site, "/private"), "Hi alice."
    )

    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert RECEIVED == []


async def test_an_account_already_followed_is_never_clicked_again(driver, site):
    """The button that unfollows people says "Following".

    Once the profile is already followed, following is not what is standing
    between us and the Message button — and the control in that spot now
    unfollows on click. Unfollowing someone the operator deliberately
    followed, in pursuit of a message that was never going to send, is the
    one outcome here that is worse than giving up.
    """
    result = await driver.send_message(
        account(), target(site, "/following"), "Hi alice."
    )

    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert RECEIVED == [], f"the Following control was clicked: {RECEIVED!r}"


async def test_following_is_not_attempted_when_it_is_turned_off(driver, site):
    """Following is a public action on the operator's own account.

    It is on by default because they asked for it, and it stays switchable
    because it is the kind of thing someone may well want to stop doing.
    """
    result = await driver.send_message(
        account(),
        target(site, "/followunlocks", follow_to_unlock=False),
        "Hi alice.",
    )

    assert result.success is False
    assert result.status == RESULT_MESSAGING_UNAVAILABLE
    assert RECEIVED == []


def test_the_follow_selector_cannot_match_a_following_button():
    """The trap that a substring match walks straight into.

    Instagram puts the label in a bare div inside the button, so the
    obvious exact-text selectors match nothing at all — measured count=0 on
    a live profile, which is why no Follow was ever clicked. The obvious
    repair is `:has-text('Follow')`, and on a profile we already follow that
    matches the *Following* button: count=1, measured on a real one. It
    would have unfollowed one person per target, silently, while looking
    like it was working.

    This pins the distinction in the selector table itself, since it is the
    kind of thing a later "simplification" undoes without noticing.
    """
    follow = " ".join(
        selector
        for tier in PlaywrightInstagramMessenger.SELECTORS["follow_button"]
        for selector in tier
    )
    assert ":has-text(" not in follow, (
        "a substring match here matches 'Following' and unfollows people"
    )
    assert ":has(:text-is('Follow'))" in follow, (
        "the label is a div inside the button, so the match has to be "
        "ancestor-aware and exact at the same time"
    )


async def test_a_following_button_is_left_alone_in_its_real_markup(driver, site):
    """The same guard, driven through a page rather than a string.

    `/following` renders the control the way Instagram does — a button
    wrapping a styled div — and reports to the server if it is ever
    clicked, which is what unfollowing someone would look like from here.
    """
    result = await driver.send_message(
        account(), target(site, "/following"), "Hi alice."
    )

    assert result.success is False
    assert RECEIVED == [], f"the Following control was clicked: {RECEIVED!r}"


# --- one tab, many targets -------------------------------------------------

async def test_one_tab_is_reused_across_targets(driver, site):
    """Sending opened a tab per target and closed it again.

    A browser launch's worth of setup several hundred times a run, and on
    a visible worker a window flickering open and shut beside whatever the
    operator was doing. The session lives in the context, not the tab, so
    navigating the same tab to the next profile is the same thing without
    the churn.
    """
    message = "Hi alice, quick question."
    context = await driver._context_for(account())

    first = await driver.send_message(account(), target(site, "/alice"), message)
    assert first.success is True, first.error
    tab = driver._pages[1]
    assert len(context.pages) == 1

    second = await driver.send_message(account(), target(site, "/alice"), message)
    assert second.success is True, second.error

    assert driver._pages[1] is tab, "a second tab was opened for the second target"
    assert len(context.pages) == 1, f"{len(context.pages)} tabs open, expected 1"
    assert len(RECEIVED) == 2


async def test_a_tab_that_dies_is_replaced_not_reused(driver, site):
    """Reuse must not mean handing out a corpse.

    A worker killed mid-job, or an operator closing the window, leaves a
    tab that cannot be navigated. The next send has to notice and build a
    fresh one rather than failing every target from then on.
    """
    message = "Hi alice, quick question."
    assert (await driver.send_message(
        account(), target(site, "/alice"), message
    )).success is True

    dead = driver._pages[1]
    await dead.close()          # as if the window had been shut

    result = await driver.send_message(account(), target(site, "/alice"), message)

    assert result.success is True, result.error
    assert driver._pages[1] is not dead, "the closed tab was handed out again"


# --- following, as its own campaign activity -------------------------------
#
# `follow_target` is not `_follow_first`. The first is a follow campaign; the
# second is the follow that a *message* sometimes needs first. They were not
# equally well served: `follow_target` asked only
# `_profile_follow_control`, which is a hook that the base class answers with
# `(None, None)` and only X overrides. So on Instagram every follow job ended
# in `messaging_unavailable` — 1,000 of them on one campaign, with the
# profiles opening one after another and nothing ever being followed.

async def test_a_follow_campaign_actually_follows_on_instagram(driver, site):
    """The bug, reproduced: a plain profile with a Follow button.

    Instagram does not override `_profile_follow_control`, so before the
    selector-table fallback existed this returned `messaging_unavailable`
    and the profile was left unfollowed.
    """
    result = await driver.follow_target(
        account(), target(site, "/followunlocks"))
    assert result.success, (
        f"a profile with a Follow button was not followed: "
        f"{result.status} — {result.error}"
    )
    assert result.status == RESULT_SENT
    assert "UNFOLLOWED" not in "".join(RECEIVED)


async def test_a_follow_campaign_counts_an_already_followed_profile_as_done(
    driver, site
):
    """Already followed is success, and the button is never pressed.

    This is the half the operator noticed first: profiles they already
    followed were opened, not marked, and reported as failures. The control
    on this page is the one that *unfollows*, and it tells the server if it
    is ever clicked.
    """
    result = await driver.follow_target(account(), target(site, "/following"))
    assert result.success, (
        f"an already-followed profile was not counted as done: {result.status}"
    )
    assert result.status == RESULT_ALREADY_FOLLOWING, (
        "reported as a send, so a report cannot tell a follow that landed "
        "from one that was never needed — which is how 56 'sent' turned out "
        "to be 16 actual follows"
    )
    assert result.status != RESULT_SENT
    assert result.detail.get("already") == "following"
    assert "UNFOLLOWED" not in "".join(RECEIVED), (
        "the Following control was pressed — that unfollows somebody"
    )


async def test_a_private_profile_is_requested_and_counted(driver, site):
    """A request pending is done too — there is nothing further to press."""
    result = await driver.follow_target(account(), target(site, "/private"))
    assert result.success, f"a private profile was not handled: {result.status}"
    assert result.status == RESULT_FOLLOW_REQUESTED, (
        "a pending request is not a follow — the following count does not "
        "move until a person accepts it, and they may never"
    )


async def test_a_profile_with_no_follow_control_still_reports_it(driver, site):
    """The fallback must not turn a genuinely absent control into a success."""
    result = await driver.follow_target(account(), target(site, "/gone"))
    assert not result.success


async def test_a_suggestions_row_cannot_answer_for_the_profile(driver, site):
    """The profile's own Follow button must win over a suggestion's.

    The page has one Follow button that belongs to @alice and three buttons
    that belong to strangers, two of them reading "Following". A page-wide
    match finds a stranger's first and concludes the job is already done.

    The assertion is not on the status alone — a status can be right for the
    wrong reason. The stub reports to the server when @alice's own button is
    pressed, so this checks the follow actually happened.
    """
    result = await driver.follow_target(account(), target(site, "/suggestions"))
    assert "FOLLOWED-ALICE" in "".join(RECEIVED), (
        "the profile's own Follow button was never pressed — a suggestion's "
        "'Following' button answered for it, and the job was recorded as done "
        "while the account followed nobody"
    )
    assert result.success
    assert result.status == RESULT_SENT, (
        f"expected a real follow, got {result.status}"
    )


async def test_a_follow_is_seen_when_the_button_carries_an_icon(driver, site):
    """The follow landed; the driver said "follow limit" and paused the
    campaign for six hours — three times in two minutes on 2026-09-24,
    on profiles that were all, in fact, followed."""
    result = await driver.follow_target(account(), target(site, "/followchevron"))
    assert result.status == RESULT_SENT, (
        f"a follow that landed was reported as {result.status}: {result.error}")
    assert "UNFOLLOWED" not in "".join(RECEIVED)


async def test_an_already_followed_profile_with_the_icon_is_left_alone(driver, site):
    result = await driver.follow_target(account(), target(site, "/followingchevron"))
    assert result.status == RESULT_ALREADY_FOLLOWING, result.status
    assert "UNFOLLOWED" not in "".join(RECEIVED), (
        "the Following control was pressed — that unfollows somebody")


async def test_a_follow_the_page_is_slow_to_show_is_checked_before_blaming_a_limit(
        driver, site, monkeypatch):
    """A limit pauses the campaign for hours, so it is not declared on a
    button that simply had not updated yet. The profile is reloaded first."""
    from services.outreach.browser import playwright_base
    monkeypatch.setattr(playwright_base, "FOLLOW_CONFIRM_POLLS", 2)
    result = await driver.follow_target(account(), target(site, "/slowfollow"))
    assert "SLOWFOLLOWED" in RECEIVED, "the profile's own button was not pressed"
    assert result.status == RESULT_SENT, (
        f"a follow that landed was reported as {result.status}: {result.error}")


async def test_a_real_limit_is_still_a_limit_after_the_reload(driver, site, monkeypatch):
    from services.outreach.browser import playwright_base
    from services.outreach.constants import RESULT_FOLLOW_LIMITED
    monkeypatch.setattr(playwright_base, "FOLLOW_CONFIRM_POLLS", 2)
    result = await driver.follow_target(account(), target(site, "/ignoredfollow"))
    assert result.status == RESULT_FOLLOW_LIMITED, result.status


# --- unfollowing -------------------------------------------------------


async def test_unfollow_goes_through_the_menu_and_is_confirmed_by_reload(driver, site):
    from services.outreach.constants import RESULT_SENT
    result = await driver.unfollow_target(account(), target(site, "/unfollowme"))
    assert result.status == RESULT_SENT, f"{result.status}: {result.error}"
    assert "UNFOLLOWED" in RECEIVED
    assert "FOLLOWED-STRANGER" not in RECEIVED and "FOLLOWED" not in RECEIVED


async def test_unfollowing_someone_not_followed_presses_nothing(driver, site):
    """Pressing Follow here would *follow* them. It must never happen."""
    from services.outreach.constants import RESULT_NOT_FOLLOWING
    result = await driver.unfollow_target(account(), target(site, "/notfollowed"))
    assert result.success and result.status == RESULT_NOT_FOLLOWING, result.status
    assert RECEIVED == [], f"something was pressed: {RECEIVED}"


async def test_unfollowing_a_deleted_profile_gives_up_at_once(driver, site):
    """It used to wait out every read for a button that would never come:
    3½ minutes per gone account in a live run (2026-09-28)."""
    import time
    from services.outreach.constants import RESULT_PROFILE_UNAVAILABLE
    started = time.monotonic()
    result = await driver.unfollow_target(account(), target(site, "/gone"))
    assert result.status == RESULT_PROFILE_UNAVAILABLE, f"{result.status}: {result.error}"
    assert time.monotonic() - started < 20
    assert RECEIVED == [], f"something was pressed: {RECEIVED}"


async def test_an_unfollow_that_leaves_follow_back_is_done(driver, site):
    """They follow this account: the button reads "Follow Back" afterwards.
    Unread, 13 unfollows that worked came back "could not tell" (2026-09-28)."""
    from services.outreach.constants import RESULT_SENT
    result = await driver.unfollow_target(account(), target(site, "/unfollowback"))
    assert result.status == RESULT_SENT, f"{result.status}: {result.error}"
    assert RECEIVED == ["UNFOLLOWED"], RECEIVED


async def test_follow_back_is_not_followed_and_nothing_is_pressed(driver, site):
    from services.outreach.constants import RESULT_NOT_FOLLOWING
    result = await driver.unfollow_target(account(), target(site, "/followsback"))
    assert result.success and result.status == RESULT_NOT_FOLLOWING, result.status
    assert RECEIVED == [], f"something was pressed: {RECEIVED}"


async def test_following_someone_who_follows_back_presses_their_own_button(driver, site):
    """Not the first suggestion's "Follow" — a stranger."""
    await driver.follow_target(account(), target(site, "/followsback"))
    assert "FOLLOWED-STRANGER" not in RECEIVED, RECEIVED
    assert "FOLLOWED" in RECEIVED, RECEIVED


async def test_an_unfollow_the_site_does_not_keep_is_not_reported_as_done(driver, site):
    from services.outreach.constants import RESULT_FOLLOW_DISCARDED
    result = await driver.unfollow_target(account(), target(site, "/unfollowlies"))
    assert result.status == RESULT_FOLLOW_DISCARDED, f"{result.status}: {result.error}"
