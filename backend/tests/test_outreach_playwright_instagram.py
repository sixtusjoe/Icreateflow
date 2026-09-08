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
