"""TikTok's DM surface: the selector table, and nothing else.

Every behaviour lives in `playwright_base.PlaywrightMessenger`. What is
here is the part that is genuinely about tiktok.com — which elements to
look for, and the traps in finding them. The comments matter: most of these
entries exist because a looser version of them cost a live target.
"""
from __future__ import annotations

import re
import time
from typing import Any

from services.outreach.browser.playwright_base import (
    CLICK_MS,
    COMPOSER_MS,
    SETTLE_MS,
    PlaywrightMessenger,
)

#: "View 3 replies" — the control hiding most of a video's commenters.
#: Both halves of a thread. TikTok opens a reply thread a page at a time:
#: "View 34 replies" reveals three and relabels itself "View 31 more", so
#: matching only the opening label reads the first page of every thread and
#: leaves the rest — on one video the abandoned controls read "View 31
#: more", "View 27 more", "View 15 more".
_REPLY_LABEL = re.compile(r"^View \d[\d,.]* (?:repl(?:y|ies)|more)$", re.I)

#: Ordered fallbacks — the first selector that resolves wins.
TIKTOK_SELECTORS: dict[str, Any] = {
    # Something proving the profile actually rendered, so the button checks
    # don't run against a shell that has not hydrated yet.
    # Only things that exist once THIS profile's data has rendered. A bare
    # "h1" was in here, and `_first_visible` races its selectors: the shell
    # paints a heading before any profile data arrives, so the gate passed
    # on an empty page every time and the Message-button search then ran
    # against markup that did not exist yet.
    "profile_loaded": (
        "[data-e2e='user-title']",
        "[data-e2e='user-subtitle']",
        "[data-e2e='followers-count']",
    ),
    "profile_missing": (
        "text=Couldn't find this account",
        "text=Couldn't find this account.",
        "text=This account is private",
    ),
    "login_wall": (
        "[data-e2e='login-button']",
        "text=Log in to TikTok",
        "text=Sign up for TikTok",
    ),
    # Tiered, most specific first. Ordering matters: "anything containing the
    # word Message" would happily match a nav item, and _first_visible races
    # its selectors, so the loosest could win. Tiers are tried in sequence;
    # only the selectors inside one tier race each other.
    "message_button": (
        ("[data-e2e='message-button']", "[data-e2e='message-button-inline']"),
        # TikTok builds most of its controls out of divs, not <button>.
        #
        # `:text-is` (exact) rather than `:has-text` (substring) is load
        # bearing: TikTok's left navigation has a "Messages" entry, which
        # contains the word "Message", and because _first_visible races its
        # selectors that nav link can win over the profile's own control.
        # Clicking it navigates to the inbox — which is exactly the
        # "composer never opened, page offers inbox-title|…" failure seen in
        # production.
        (
            "button:text-is('Message')",
            "a:text-is('Message')",
            "div[role='button']:text-is('Message')",
            "[role='button']:text-is('Message')",
        ),
    ),
    # The profile's own Follow control. Tiered for the same reason the
    # Message button is: TikTok's left navigation has a "Following" entry,
    # and a loose match on that word would find it instead. The generic tier
    # is exact-text and excludes links, because the nav entry is a link.
    "follow_button": (
        ("[data-e2e='follow-button']",),
        (
            "button:text-is('Follow')",
            "div[role='button']:text-is('Follow')",
        ),
    ),
    #: Already followed — the same control, showing its other state.
    "already_following": (
        "[data-e2e='follow-button']:has-text('Following')",
        "[data-e2e='follow-button']:has-text('Friends')",
        "button:text-is('Following')",
        "div[role='button']:text-is('Following')",
    ),
    # The editable itself, before the wrapper around it.
    #
    # `message-input-area` is a container: it holds the editable *and*
    # TikTok's "Send a message..." placeholder. Typing into a container
    # is not typing into the box, and reading its text after a send finds
    # the placeholder — which is what made every delivered message report
    # "the message is still sitting in the composer".
    "message_input": (
        "[data-e2e='message-input-area'] div[contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
        "[data-e2e='message-input-area']",
    ),
    # The DM inbox: a list of conversations with none of them open. Landing
    # here after clicking Message means no thread was started, so there is
    # nothing to type into.
    "messages_view": (
        "[data-e2e='chat-list']",
        "[data-e2e='inbox-title']",
        "[data-e2e='chat-list-item']",
    ),
    "send_button": (
        "[data-e2e='message-send']",
        "button[type='submit']:has-text('Send')",
        "svg[data-e2e='message-send-icon']",
    ),
    "sent_confirmation": (
        "[data-e2e='chat-item']",
        "div[class*='DivChatItem']",
    ),
    # TikTok's own error page. It replaces the whole profile — no avatar,
    # no buttons — and it is what the site serves after a verification
    # puzzle often enough to matter. Without this the empty page reads as
    # "this profile has no Message button".
    "site_error": (
        "text=Something went wrong",
        "text=Please try again later",
        "text=Sorry about that!",
    ),
    # TikTok takes the message, puts it in the thread, and then refuses to
    # deliver it — an error marker beside the message and this notice under
    # it. Both delivery checks pass in that state: the composer does clear,
    # and the text really is on the page. Without this the queue reports a
    # send that never happened, which is the exact failure the
    # composer-cleared check exists to prevent.
    "message_refused": (
        "text=has not been sent",
        "text=may be in violation of our Community Guidelines",
        "text=to protect our community",
    ),
    # --- discovery ---------------------------------------------------------
    #
    # Every entry below was read off a live video page. TikTok serves none
    # of this to a headless browser: identical code found zero comment
    # hooks headless and twelve headed, which is why discovery must run
    # with a visible window.
    #
    # The commenter's handle is a link inside the username element, at both
    # levels — `comment-username-1` for a top-level comment and
    # `comment-username-2` for a reply.
    "post_people": (
        "[data-e2e^='comment-username'] a[href^='/@']",
        "[data-e2e='browse-user-avatar']",
    ),
    "post_link": (
        "a[href*='/video/']",
        "[data-e2e='user-post-item'] a",
    ),
    # The comment panel is collapsed until this is clicked — and it must be
    # a real click. A JS el.click() does nothing at all.
    "comment_toggle": (
        "[data-e2e='comment-icon']",
    ),
    # "View 3 replies" under a comment. Most of a video's comments live
    # behind these: a 535-comment video renders about 150 at the top level
    # and hides the rest.
    "comment_replies": (
        "[data-e2e='comment-reply-1']",
    ),
    # The panel scrolls inside itself, not the page.
    "scroll_container": (
        "div[class*='DivCommentListContainer']",
        "div[class*='DivCommentMain']",
    ),
    "hashtag_url": (),
    "search_input": (
        "[data-e2e='search-user-input']",
        "input[data-e2e='search-box']",
    ),
    "search_result": (
        "[data-e2e='search-user-container']",
        "[data-e2e='search_top-item']",
    ),
    "rate_limited": (
        "text=You're sending messages too fast",
        "text=Too many attempts",
    ),
    # TikTok's human-verification puzzle. It renders *over* a perfectly
    # normal profile: the Message button is right there and visible, so
    # every check above passes and the click simply never lands. Without
    # this the driver reports "no Message button" and the queue skips a
    # good target for good.
    #
    # Matched by container id/class as well as text, because the wording is
    # localised and the puzzle has several variants (slider, rotate, pick
    # two objects).
    "verification_challenge": (
        "#captcha-verify-container",
        "#captcha_container",
        "div[id*='captcha-verify']",
        "div[class*='captcha_verify_container']",
        "text=Drag the slider to fit the puzzle",
        "text=Verify to continue",
        "text=Slide to verify",
        "text=Verification failed",
    ),
}


#: TikTok's own consent banner sits in a shadow root, so it needs piercing
#: selectors the generic list has no reason to carry.
TIKTOK_OVERLAY_DISMISS = (
    "tiktok-cookie-banner >>> button:has-text('Decline all')",
    "tiktok-cookie-banner >>> button:has-text('Allow all')",
) + PlaywrightMessenger.OVERLAY_DISMISS


class PlaywrightTikTokMessenger(PlaywrightMessenger):
    """TikTok. The engine, plus the table above.

    No `attach_image` entry: TikTok's web composer sends text only. A
    campaign with an image assigned to a TikTok account fails saying so,
    rather than sending the text alone and reporting success.
    """

    PLATFORM = "tiktok"
    OVERLAY_DISMISS = TIKTOK_OVERLAY_DISMISS
    SELECTORS = TIKTOK_SELECTORS
    SITE_URL = "https://www.tiktok.com"
    SEARCH_URL = "https://www.tiktok.com/search"
    SEARCH_QUERY_URL = "https://www.tiktok.com/search/user?q={q}"
    name = "playwright_tiktok"

    #: How many times to alternate scrolling and opening reply threads.
    #: Opening threads makes the panel taller, which lets more top-level
    #: comments load, which brings more threads — one pass of each finds
    #: about a third of the people.
    #: An upper bound, not a target: the loop stops when passes stop
    #: producing people. Six was a target, and it cut a video off while it
    #: was still gaining thirty a pass.
    COMMENT_PHASES = 60
    #: Consecutive passes that must find nobody new and open nothing.
    QUIET_PHASES = 2
    #: The longest any one video may be worked.
    PANEL_BUDGET_MS = 2700000
    #: How long to wait for the comment control. Generous on purpose: the
    #: page hydrates well after it starts playing the video.
    COMMENT_PANEL_MS = 30000
    #: How many reloads to spend on a page that came up as a skeleton.
    HYDRATE_RELOADS = 2
    #: A thread opens a page at a time, so one with 34 replies costs a
    #: dozen clicks on its own. 400 was not enough for a video's worth.
    REPLY_CLICKS = 2000
    REPLY_BUDGET_MS = 600000

    # One message, always.
    #
    # TikTok allows a single message before the recipient accepts the
    # request — "You can only send up to 1 message before this user accepts
    # your message request" — so a template that splits does not just look
    # untidy, it spends the one attempt on the first line and has the rest
    # refused. Seen on @yzy678: three bubbles, two of them marked failed.
    TYPE_AS_ONE_INSERT = True

    def profile_url(self, username: str) -> str:
        return f"{self.SITE_URL}/@{username.strip().lstrip('@')}"

    def username_from_url(self, href: str) -> str:
        """`/@someone` → `someone`. Anything else → ""."""
        if not href:
            return ""
        path = href.split("?")[0].split("#")[0]
        if path.startswith("http"):
            path = path.split("//", 1)[-1]
            path = path.split("/", 1)[1] if "/" in path else ""
        parts = [p for p in path.split("/") if p]
        if not parts or not parts[0].startswith("@"):
            return ""
        username = parts[0][1:]
        if not username or len(username) > 24:
            return ""
        if not all(c.isalnum() or c in "._" for c in username):
            return ""
        return username

    async def _people_on_post(self, page, post_url: str,
                              scroll_rounds: int = 0) -> list[str]:
        """Everyone who commented on a video, replies included.

        The base version reads profile links off a loaded page, which is
        right for Instagram and finds nothing here: TikTok keeps comments
        behind a collapsed panel, caps the top-level list, and hides the
        rest inside reply threads.

        So: open the panel with a real click, then alternate scrolling the
        panel with opening every "View N replies" until neither yields
        anyone new.
        """
        seen: dict[str, None] = {}
        try:
            await page.goto(self._absolute(post_url),
                            wait_until="domcontentloaded", timeout=self._timeout)
            await page.wait_for_timeout(SETTLE_MS)
            await self._dismiss_overlays(page)
            for _ in range(2):
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(600)

            toggle = await self._first_visible(
                page, self.SELECTORS["comment_toggle"],
                timeout_ms=self.COMMENT_PANEL_MS)
            if toggle is None:
                # TikTok serves the player and hydrates its chrome
                # separately, and when that second half does not arrive the
                # video plays over a page of grey placeholders with no
                # comment control anywhere on it. That is indistinguishable
                # from a video with comments turned off, and it was
                # reported with the same words. Reloading is what shifts
                # it; two videos in a row came back empty without this.
                print(f"[discovery] no comment control yet on {post_url} — "
                      f"the page may not have hydrated; reloading", flush=True)
                for attempt in range(self.HYDRATE_RELOADS):
                    try:
                        await page.reload(wait_until="domcontentloaded",
                                          timeout=self._timeout)
                    except Exception:  # noqa: BLE001 — report below
                        break
                    await page.wait_for_timeout(SETTLE_MS * 2)
                    await self._dismiss_overlays(page)
                    for _ in range(2):
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(400)
                    toggle = await self._first_visible(
                        page, self.SELECTORS["comment_toggle"],
                        timeout_ms=self.COMMENT_PANEL_MS)
                    if toggle is not None:
                        print(f"[discovery] comment control appeared after "
                              f"reload {attempt + 1}", flush=True)
                        break
            if toggle is None:
                print(f"[discovery] no comment control on {post_url}", flush=True)
                return []
            # Real click: a JS click does not open this.
            await toggle.click(timeout=CLICK_MS)
            await page.wait_for_timeout(SETTLE_MS * 2)

            await self._mark_comment_scroller(page)

            async def collect() -> None:
                for name in await self._collect_profile_links(
                        page, self.SELECTORS["post_people"]):
                    seen.setdefault(name)

            quiet_phases, phase = 0, 0
            panel_deadline = time.monotonic() + (self.PANEL_BUDGET_MS / 1000)
            while phase < self.COMMENT_PHASES:
                phase += 1
                if time.monotonic() > panel_deadline:
                    print(f"[discovery] stopped after "
                          f"{self.PANEL_BUDGET_MS // 1000}s on this video with "
                          f"{len(seen)} people", flush=True)
                    break
                before = len(seen)
                # Back to the top first, so each phase re-walks the whole
                # list — the replies opened last time are inline now, and
                # the rows they sit between were recycled away long ago.
                if phase > 1:
                    await page.evaluate("""() => {
                        const el = document.querySelector("[data-icf-comments='1']");
                        if (el) el.scrollTop = 0;
                    }""")
                    await page.wait_for_timeout(SETTLE_MS)
                    await collect()
                await self._scroll_comments(page, collect)
                await collect()
                opened = await self._open_reply_threads(page, collect)
                await collect()
                print(f"[discovery] comments phase {phase}: {len(seen)} people "
                      f"(opened {opened} thread(s))", flush=True)
                # Stop when passes stop producing, not after a fixed
                # count. A cap of six ended a run that was still finding
                # fifteen to thirty new people per pass — the same mistake
                # as judging a scroll by rounds instead of by growth.
                if opened == 0 and len(seen) == before:
                    quiet_phases += 1
                    if quiet_phases >= self.QUIET_PHASES and phase > 1:
                        break
                else:
                    quiet_phases = 0
        except Exception as exc:  # noqa: BLE001 — one bad video is not fatal
            print(f"[discovery] comments on {post_url} failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        return list(seen)

    async def _mark_comment_scroller(self, page) -> None:
        """Tag whatever actually scrolls, walking up from a comment row."""
        await page.evaluate("""() => {
            const row = document.querySelector("[data-e2e='comment-level-1']");
            let el = row && row.parentElement;
            for (let i = 0; i < 12 && el; i++, el = el.parentElement) {
                if (el.scrollHeight > el.clientHeight + 60) {
                    el.setAttribute('data-icf-comments', '1');
                    return;
                }
            }
        }""")

    async def _scroll_comments(self, page, collect=None) -> int:
        """Scroll the comment panel until it stops growing.

        `collect` is called after every step, and has to be: TikTok recycles
        the rows, so a comment scrolled past is removed from the page.
        Reading once at the end returned the last screenful — five people
        out of sixty in the test, 184 out of a 499-comment video in
        production — and nothing distinguishes that from a short list.

        One screen at a time rather than jumping to the bottom, for the
        same reason: a jump skips every row in between and they are never
        rendered again.
        """
        quiet, tallest = 0, 0
        for _ in range(240):
            await page.evaluate("""() => {
                const el = document.querySelector("[data-icf-comments='1']");
                if (!el) return;
                const step = Math.max(el.clientHeight - 60, 80);
                const next = el.scrollTop + step;
                // Past the end, sit at the bottom so more can load.
                el.scrollTop = next >= el.scrollHeight ? el.scrollHeight : next;
            }""")
            await page.wait_for_timeout(1400)
            if collect is not None:
                await collect()
            height = await page.evaluate("""() => {
                const el = document.querySelector("[data-icf-comments='1']");
                return el ? el.scrollHeight : 0;
            }""")
            at_end = await page.evaluate("""() => {
                const el = document.querySelector("[data-icf-comments='1']");
                if (!el) return true;
                return el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
            }""")
            # Quiet means the list stopped growing *and* there is nothing
            # below — still working down a loaded list is not being stuck.
            quiet = 0 if (height > tallest or not at_end) else quiet + 1
            tallest = max(tallest, height)
            # Patient on purpose: a short fuse stopped this at a third of
            # the list, which looked like a video with few comments.
            if quiet >= 20:
                break
        return tallest

    async def _open_reply_threads(self, page, collect=None) -> int:
        """Open every visible "View N replies". Real clicks only.

        Collects as it goes for the same reason the scroll does: scrolling
        a control into view recycles away whatever it scrolled past.
        """
        opened = 0
        deadline = time.monotonic() + (self.REPLY_BUDGET_MS / 1000)
        for _ in range(self.REPLY_CLICKS):
            if time.monotonic() > deadline:
                print(f"[discovery] stopped expanding threads after "
                      f"{self.REPLY_BUDGET_MS // 1000}s with {opened} opened",
                      flush=True)
                break
            try:
                one = page.get_by_text(_REPLY_LABEL).nth(0)
                if not await one.count():
                    break
                await one.scroll_into_view_if_needed(timeout=2500)
                await one.click(timeout=CLICK_MS)
                opened += 1
                await page.wait_for_timeout(400)
                if collect is not None:
                    await collect()
            except Exception:  # noqa: BLE001 — nothing left that will open
                break
        return opened
