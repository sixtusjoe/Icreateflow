"""TikTok discovery, against a local stub — never tiktok.com.

The stub copies the three things that made this hard, because a stub
without them passes while the real site returns nothing:

  * the comment panel is collapsed until the icon is clicked
  * the top-level list is capped, and the rest of the people are inside
    "View N replies" threads
  * a reply thread only opens on a click

What it cannot prove is that these selectors still match TikTok. Those
were read off a live video — `comment-username-1`, `comment-level-1`,
`comment-icon` — and confirmed to find real handles. What is untestable
here is that TikTok serves none of it to a headless browser at all.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright.async_api", reason="playwright is not installed")

from services.outreach.browser.playwright_tiktok import (  # noqa: E402
    PlaywrightTikTokMessenger,
)
from services.outreach.discovery import post_urls_in  # noqa: E402

VIDEO = """
<html><body>
  <div data-e2e="comment-icon" onclick="openComments()">Comments</div>
  <div id="panel" style="display:none">
    <div id="list" style="height:120px;overflow:auto">
      <div id="rows"></div>
    </div>
  </div>
  <script>
    // Top level, capped — as TikTok caps it.
    const TOP = ['alice','bob','carol','dave'];
    // The rest of the people, hidden behind reply threads.
    const REPLIES = {alice: ['erin','frank'], carol: ['grace']};
    function row(name, level) {
      return '<div data-e2e="comment-level-' + level + '">'
           + '<div data-e2e="comment-username-' + level + '">'
           + '<a href="/@' + name + '">' + name + '</a></div></div>';
    }
    function openComments() {
      document.getElementById('panel').style.display = 'block';
      let html = '';
      for (const n of TOP) {
        html += row(n, 1);
        if (REPLIES[n]) {
          html += '<p class="more" onclick="expand(\\'' + n + '\\')">View '
               + REPLIES[n].length + ' replies</p>';
        }
      }
      document.getElementById('rows').innerHTML = html;
    }
    function expand(who) {
      const extra = REPLIES[who].map(n => row(n, 2)).join('');
      document.getElementById('rows').insertAdjacentHTML('beforeend', extra);
      delete REPLIES[who];
      for (const p of document.querySelectorAll('p.more')) {
        if (p.innerText.indexOf('View') === 0 && !REPLIES[who]) {
          // Remove just this one, as TikTok replaces the control.
        }
      }
      const ps = Array.from(document.querySelectorAll('p.more'));
      for (const p of ps) {
        const m = p.getAttribute('onclick') || '';
        if (m.indexOf("'" + who + "'") >= 0) p.remove();
      }
    }
  </script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(VIDEO.encode())

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
def _fast(monkeypatch):
    monkeypatch.setattr("services.outreach.browser.playwright_base.DEBUG_DIR", "")
    for name, value in (("SETTLE_MS", 200), ("COMPOSER_MS", 2000), ("CLICK_MS", 2000)):
        monkeypatch.setattr(f"services.outreach.browser.playwright_base.{name}", value)


@pytest.fixture
async def driver():
    d = PlaywrightTikTokMessenger(headless=True, timeout_ms=8000)
    try:
        await d.startup()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium is not available: {exc}")
    try:
        yield d
    finally:
        await d.shutdown()


def account() -> dict:
    return {"id": 1, "name": "Discovery", "platform": "tiktok",
            "session_state": json.dumps({"cookies": [], "origins": []})}


async def test_commenters_come_from_behind_the_collapsed_panel(driver, site):
    """Nothing is readable until the comment icon is clicked."""
    context = await driver._context_for(account())
    page = await context.new_page()
    names = await driver._people_on_post(page, f"{site}/@someone/video/1")
    assert "alice" in names and "bob" in names, names


async def test_the_people_inside_reply_threads_are_not_missed(driver, site):
    """Most of a video's commenters are behind "View N replies".

    A 535-comment video rendered about 150 at the top level; the rest were
    in threads. Reading only the top level finds a third of the people and
    looks like the whole list, which is exactly what happened.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    names = await driver._people_on_post(page, f"{site}/@someone/video/1")

    for hidden in ("erin", "frank", "grace"):
        assert hidden in names, f"{hidden} was inside a reply thread: {names}"
    assert len(set(names)) == 7, names


def test_a_video_link_is_routed_to_the_comment_reader():
    """Seeds that are links to posts are a different job from account names."""
    seeds = ["https://www.tiktok.com/t/ZP83Mh84x/", "@someaccount",
             "https://www.tiktok.com/@a/video/123", "nike"]
    assert post_urls_in(seeds) == [
        "https://www.tiktok.com/t/ZP83Mh84x/",
        "https://www.tiktok.com/@a/video/123",
    ]


def test_only_a_profile_path_is_read_as_a_handle():
    d = PlaywrightTikTokMessenger
    assert d.username_from_url(d, "/@some.one") == "some.one"
    for junk in ("/video/123", "/tag/x", "", "/@", "/foryou"):
        assert d.username_from_url(d, junk) == "", junk
