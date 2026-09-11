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


#: A comment list that recycles its rows, which is what TikTok's does: only
#: the handful of rows near the scroll position exist in the DOM, and
#: scrolling past a row destroys it. Reading the list once at the bottom
#: therefore returns the last screenful and nothing else.
VIRTUALISED = """
<html><body>
  <div data-e2e="comment-icon" onclick="openComments()">Comments</div>
  <div id="panel" style="display:none">
    <div id="list" style="height:200px;overflow:auto" onscroll="render()">
      <div id="spacer" style="position:relative"><div id="rows"></div></div>
    </div>
  </div>
  <script>
    const ROW_H = 40, WINDOW = 6;
    const PEOPLE = [];
    for (let i = 0; i < 60; i++) PEOPLE.push('person' + i);
    function openComments() {
      document.getElementById('panel').style.display = 'block';
      document.getElementById('spacer').style.height =
        (PEOPLE.length * ROW_H) + 'px';
      render();
    }
    function render() {
      const list = document.getElementById('list');
      const first = Math.floor(list.scrollTop / ROW_H);
      const last = Math.min(first + WINDOW, PEOPLE.length);
      let html = '';
      for (let i = first; i < last; i++) {
        html += '<div data-e2e="comment-level-1" style="position:absolute;top:'
             + (i * ROW_H) + 'px">'
             + '<div data-e2e="comment-username-1">'
             + '<a href="/@' + PEOPLE[i] + '">' + PEOPLE[i] + '</a></div></div>';
      }
      document.getElementById('rows').innerHTML = html;
    }
  </script>
</body></html>
"""


#: The skeleton TikTok serves when the page does not finish hydrating: the
#: video element is there and the chrome — comment icon included — never
#: arrives. Reloading is what shifts it, so this page hydrates only on the
#: second request.
SKELETON_THEN_REAL = """
<html><body>
  <div data-e2e="feed-video">video</div>
  <div class="skeleton">loading</div>
</body></html>
"""


#: A thread that opens a page at a time, which is what TikTok does: the
#: control says "View 5 replies", clicking it reveals two, and the control
#: becomes "View 3 more". Stopping at the first label leaves most of the
#: thread unread.
PAGED_REPLIES = """
<html><body>
  <div data-e2e="comment-icon" onclick="openComments()">Comments</div>
  <div id="panel" style="display:none"><div id="rows"></div></div>
  <script>
    const HIDDEN = ['r1','r2','r3','r4','r5'];
    function row(name, level) {
      return '<div data-e2e="comment-level-' + level + '">'
           + '<div data-e2e="comment-username-' + level + '">'
           + '<a href="/@' + name + '">' + name + '</a></div></div>';
    }
    function openComments() {
      document.getElementById('panel').style.display = 'block';
      document.getElementById('rows').innerHTML =
        row('alice', 1)
        + '<p class="more" onclick="expand()">View ' + HIDDEN.length
        + ' replies</p>';
    }
    function expand() {
      const take = HIDDEN.splice(0, 2);
      const html = take.map(n => row(n, 2)).join('');
      const p = document.querySelector('p.more');
      p.insertAdjacentHTML('beforebegin', html);
      if (HIDDEN.length) p.innerText = 'View ' + HIDDEN.length + ' more';
      else p.remove();
    }
  </script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.path.startswith("/paged"):
            self.wfile.write(PAGED_REPLIES.encode())
            return
        if self.path.startswith("/virtual"):
            body = VIRTUALISED
        elif self.path.startswith("/skeleton"):
            # First request is the dead skeleton; a reload gets the page.
            seen = getattr(self.server, "_skeleton_hits", 0)
            self.server._skeleton_hits = seen + 1
            body = SKELETON_THEN_REAL if seen == 0 else VIDEO
        else:
            body = VIDEO
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

async def test_a_recycled_comment_list_is_read_as_it_scrolls(driver, site):
    """Everyone, not just whoever is on screen when the scrolling stops.

    TikTok's comment panel recycles its rows: scrolling past a comment
    removes it from the page. The reader scrolled the whole panel to the
    bottom first and collected afterwards, so it saw one screenful — the
    last one — plus whatever had survived. On a video with 499 comments it
    returned 184 people and reported that as the whole list, which is
    indistinguishable from a video that simply has fewer commenters.

    Sixty people here, six on screen at a time.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    found = await driver._people_on_post(page, f"{site}/virtual")
    await page.close()
    assert len(found) == 60, (
        f"read {len(found)} of 60 — the rest were recycled away unread: "
        f"{sorted(found)[:8]}"
    )


async def test_a_page_that_never_hydrated_is_reloaded_not_written_off(driver, site):
    """A skeleton is not a video without comments.

    TikTok serves the player and then hydrates its chrome separately. When
    that second half does not arrive the video plays over a page of grey
    placeholders and there is no comment control anywhere on it — which the
    reader reported as "no comment control", the same words it uses for a
    video that genuinely has comments turned off.

    Two of two videos came back with zero commenters that way. Reloading is
    what shifts it, so the reader has to try that before giving up.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    found = await driver._people_on_post(page, f"{site}/skeleton")
    await page.close()
    assert found, "gave up on a page that only needed reloading"
    assert "alice" in found


async def test_a_thread_is_opened_all_the_way_down(driver, site):
    """"View 34 replies" becomes "View 31 more" — and that is the rest of it.

    Clicking the first control reveals a page of replies and relabels
    itself. The pattern matched only the opening label, so every thread
    gave up its first few replies and kept the rest: on one video the
    controls left behind read "View 31 more", "View 27 more", "View 15
    more". Those people were never on the page to be read.
    """
    context = await driver._context_for(account())
    page = await context.new_page()
    found = await driver._people_on_post(page, f"{site}/paged")
    await page.close()
    missing = {f"r{i}" for i in range(1, 6)} - set(found)
    assert not missing, f"left behind in the thread: {sorted(missing)}"
