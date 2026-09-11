"""Instagram's DM surface: the selector table, and nothing else.

Every behaviour is inherited from `playwright_base.PlaywrightMessenger` —
the same engine TikTok uses, including all of the delivery checking that
exists because this system once reported sends that never happened.

A warning about what is and is not proven here. The engine is exercised by
the driver suite and by a day of real TikTok traffic. These selectors are
not: they are written from Instagram's published DM interface and covered by
stub pages only. Until a send has been watched against instagram.com, treat
every entry below as a hypothesis. The failure they will produce is the
honest one — `messaging_unavailable` or `unexpected_page`, neither of which
is terminal — rather than a wrong send.

Instagram-specific traps worth knowing:

* Instagram's own left navigation has a "Messages" entry, exactly like
  TikTok's, and clicking it navigates to the inbox instead of opening a
  thread. Every generic match here is exact-text and excludes links for
  that reason — it is the bug that cost a live target on TikTok.
* The composer is a contenteditable, not an input, and Instagram often has
  no visible Send button until text is entered; the engine falls back to
  pressing Enter, which is the normal way to send here.
* "Message" appears on the profile as a button, but on a profile that does
  not accept DMs it is simply absent rather than disabled.
"""
from __future__ import annotations

import re
from typing import Any

from services.outreach.browser.playwright_base import SETTLE_MS, PlaywrightMessenger

#: A header line that is a statistic rather than someone's name.
_IS_STAT = re.compile(r"^[\d.,]+\s*[KkMm]?\s+(posts?|followers?|following)$")


def _as_int(raw: str) -> int | None:
    """"270K" -> 270000. Instagram abbreviates once the number is large."""
    text = raw.strip().replace(",", "").replace(" ", "")
    multiplier = 1
    if text[-1:].lower() == "k":
        multiplier, text = 1_000, text[:-1]
    elif text[-1:].lower() == "m":
        multiplier, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None

#: Ordered fallbacks — the first selector that resolves wins.
INSTAGRAM_SELECTORS: dict[str, Any] = {
    # Something proving the profile rendered, so the checks below are not
    # racing an empty shell.
    # No bare headings: they are in the shell before the profile is, and
    # racing selectors means the loosest one decides. 317 targets in one
    # campaign were filed as "no Message button" — the page had not
    # rendered when we looked.
    "profile_loaded": (
        "header section",
        "main header",
    ),
    "profile_missing": (
        "text=Sorry, this page isn't available.",
        "text=this page isn't available",
        "text=User not found",
    ),
    "login_wall": (
        "input[name='username']",
        "text=Log in to Instagram",
        "text=Sign up to see photos",
    ),
    # Tiered, most specific first. The generic tier is exact-text and never
    # matches a link, because the left navigation's "Messages" entry would
    # otherwise win the race and navigate away from the profile.
    "message_button": (
        ("div[role='button']:text-is('Message')",),
        (
            "button:text-is('Message')",
            "[role='button']:text-is('Message')",
        ),
        # Message carries its text directly today, unlike Follow. The last
        # tier is the nested shape, in case it ever moves to match.
        (
            "div[role='button']:has(:text-is('Message'))",
            "button:has(:text-is('Message'))",
        ),
    ),
    # Instagram's composer is a contenteditable textbox, labelled for
    # accessibility rather than carrying a stable class.
    "message_input": (
        "div[role='textbox'][contenteditable='true']",
        "textarea[placeholder='Message...']",
        "div[contenteditable='true']",
    ),
    # The inbox with no conversation open: a list of threads and nowhere to
    # type. Landing here means the thread was never opened.
    "messages_view": (
        "div[role='list']",
        "text=Your messages",
        "text=Send a message to start a chat",
    ),
    # Often absent until there is text to send; the engine presses Enter
    # when this misses, which is how Instagram sends anyway.
    "send_button": (
        "div[role='button']:text-is('Send')",
        "button:text-is('Send')",
        "button[type='submit']",
    ),
    # A message that made it into the conversation.
    "sent_confirmation": (
        "div[role='row']",
        "div[data-testid='message-container']",
        "div[role='listitem']",
    ),
    # The composer's file input. Hidden behind the photo icon, which is
    # fine — a file input can be set without being visible, and clicking the
    # icon would only open an OS picker no automation can reach.
    "attach_image": (
        "div[role='dialog'] input[type='file']",
        "form input[type='file']",
        "input[type='file'][accept*='image']",
        "input[type='file']",
    ),
    # --- discovery ---
    # The search box on Instagram's own chrome. Results appear as you type;
    # there is nothing to submit.
    "search_input": (
        "input[aria-label='Search input']",
        "input[placeholder='Search']",
        "input[type='text'][aria-label*='Search']",
    ),
    # Scoped to `main` throughout, and that is the load-bearing part: the
    # left navigation carries a link to the *signed-in* account's own
    # profile, so an unscoped selector returns the discovery account as a
    # lead from every page it opens. `main` starts below the nav.
    "search_result": (
        "main a[href^='/']",
    ),
    # Post tiles on a search or hashtag page.
    "post_link": (
        "main a[href*='/p/']",
        "main a[href*='/reel/']",
    ),
    # Everyone on a post, in document order: the author first, then whoever
    # commented. One selector for both because that is how the page is
    # built — there is no `article`, no `header` and no comment `ul` on a
    # post page, which is what made every scoped guess return nothing.
    "post_people": (
        "main a[href^='/']",
    ),
    # The "N followers" link on a profile. Clicking it is the only way to
    # open that list — its URL renders the profile with no dialog at all.
    # Matched by its text, because its href is literally "#". Instagram
    # renders it as <a role="link" href="#">270K followers</a> and opens
    # the modal in JavaScript, so anything looking for a URL finds nothing.
    # "following" is a different control and does not contain "followers".
    "followers_link": (
        "main a[role='link']:has-text('followers')",
        "main a:has-text('followers')",
        "a[role='link']:has-text('followers')",
    ),
    # What to put the pointer over before scrolling. The likes list lives
    # in a dialog and the page behind it does not move, so a wheel event
    # aimed at the window scrolls nothing at all.
    "scroll_container": (
        "div[role='dialog']",
    ),
    # Instagram renders a few comments and fetches the rest behind a "+".
    # Scrolling alone misses those, so the control is pressed too.
    "load_more": (
        "button[aria-label='Load more comments']",
        "[aria-label='Load more comments']",
        "button:has-text('View all')",
    ),
    # Who liked it. Instagram puts this behind a dialog, but the dialog has
    # its own URL, so it can be asked for directly.
    "liker": (
        "div[role='dialog'] a[href^='/']",
        "main a[href^='/']",
    ),
    "rate_limited": (
        "text=Please wait a few minutes before you try again",
        "text=Try Again Later",
        "text=We limit how often",
    ),
    # Instagram's checkpoint / suspicious-login flow. A person has to clear
    # it; the engine holds the browser open for them when it is visible.
    "verification_challenge": (
        "text=Help us confirm it's you",
        "text=Confirm it's You",
        "text=We detected an unusual login attempt",
        "text=Enter the code we sent",
        "text=Suspicious Login Attempt",
    ),
    "site_error": (
        "text=Something went wrong",
        "text=There's an issue and the page could not be loaded",
        "text=Please wait a few minutes before you try again.",
    ),
    # Instagram does not show TikTok's "has not been sent" notice, but it
    # does refuse messages, and it says so.
    "message_refused": (
        "text=This message wasn't sent",
        "text=Message failed to send",
        "text=couldn't send your message",
        "text=Your message couldn't be sent",
    ),
    # Refused by the recipient rather than by Instagram. Verbatim from a
    # live send: the message rendered in the thread as three blue bubbles,
    # indistinguishable from the three genuine deliveries in the same run,
    # with this sitting quietly between them.
    "recipient_refused": (
        "text=can't receive your message",
        "text=don't allow new message requests",
    ),
    # `:text-is` matches the smallest element holding the text, and the
    # label here is a bare styled div inside the button — so the button
    # itself never matched and every Follow was missed. Measured on a live
    # profile: all three exact-text selectors returned count=0.
    #
    # `:has-text('Follow')` does match the button. It is also a substring
    # match, and on a profile we already follow it matches the *Following*
    # button — count=1, confirmed against a real followed profile. Reaching
    # for it would have unfollowed people, one per target, quietly.
    #
    # `:has(:text-is(...))` is the pair that works: ancestor-aware, so it
    # finds the button, and exact on the label, so "Following" is not
    # "Follow". Verified count=1/0 and 0/1 on the two states.
    "follow_button": (
        ("button:has(:text-is('Follow'))",),
        (
            "div[role='button']:has(:text-is('Follow'))",
            "[role='button']:has(:text-is('Follow'))",
        ),
    ),
    "already_following": (
        "button:has(:text-is('Following'))",
        "div[role='button']:has(:text-is('Following'))",
    ),
    # Kept apart from "Following" on purpose. Both mean "do not click
    # Follow", but only this one means the account is private and the
    # message is going nowhere until a person accepts the request — which
    # is a different thing to tell the operator, and a different thing to
    # do about it.
    "follow_requested": (
        "button:has(:text-is('Requested'))",
        "div[role='button']:has(:text-is('Requested'))",
    ),
}

#: Instagram's interstitials. "Not Now" covers the notifications and
#: save-login-info prompts, which appear straight after a session loads and
#: sit over everything until dismissed.
INSTAGRAM_OVERLAY_DISMISS = (
    "button:has-text('Allow all cookies')",
    "button:has-text('Decline optional cookies')",
    "button:has-text('Not Now')",
    "div[role='button']:has-text('Not Now')",
    "button:has-text('Not now')",
    "[aria-label='Close']",
)


#: Instagram paths that are not profiles. A link to /explore/ or /reels/ is
#: not a lead, and treating one as a username would put nonsense in the list.
NOT_PROFILES = {
    "explore", "reels", "reel", "p", "stories", "direct", "accounts", "about",
    "legal", "privacy", "terms", "developer", "api", "your_activity",
    "challenge", "emails", "session", "graphql", "web", "ajax", "static",
}


class PlaywrightInstagramMessenger(PlaywrightMessenger):
    """Instagram. The engine, plus the table above."""

    PLATFORM = "instagram"
    SELECTORS = INSTAGRAM_SELECTORS
    OVERLAY_DISMISS = INSTAGRAM_OVERLAY_DISMISS
    CHALLENGE_FRAME_HINTS = ("challenge", "checkpoint")
    SITE_URL = "https://www.instagram.com"
    SEARCH_URL = "https://www.instagram.com/explore/search/"
    SEARCH_QUERY_URL = "https://www.instagram.com/explore/search/keyword/?q={q}"
    name = "playwright_instagram"

    async def profile_summary(self, page, username: str) -> dict[str, Any]:
        """Read a profile from the text of the page.

        Deliberately not from selectors. Instagram's profile header has an
        empty `h1`, a `h2` holding the handle, and class names that change;
        every structured guess either missed or returned the handle twice.
        The rendered text, though, is stable and in a fixed order:

            username / display name / N posts / N followers / N following
            category
            bio lines…

        so it is parsed rather than queried.
        """
        empty = {"display_name": None, "bio": None, "followers": None}
        try:
            await page.goto(self.profile_url(username), wait_until="domcontentloaded",
                            timeout=self._timeout)
            await self._dismiss_overlays(page)
            await page.wait_for_timeout(SETTLE_MS)
            text_content = await page.inner_text("main")
        except Exception as exc:  # noqa: BLE001 — one bad profile is not fatal
            print(f"[discovery] profile @{username} failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return empty

        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
        if not lines:
            return empty

        followers = None
        match = re.search(r"([\d.,]+\s*[KkMm]?)\s+followers", text_content)
        if match:
            followers = _as_int(match.group(1))

        display_name = None
        if len(lines) > 1 and not _IS_STAT.match(lines[1]):
            display_name = lines[1][:120]

        # The bio is whatever follows the "N following" line, minus the
        # buttons that sit alongside it.
        bio_lines: list[str] = []
        started = False
        for line in lines:
            if not started:
                started = bool(re.match(r"^[\d.,]+\s*[KkMm]?\s+following$", line))
                continue
            if line in ("Follow", "Following", "Message", "Follow Back", "Requested"):
                continue
            if line.startswith("Followed by") or line.endswith("more"):
                continue
            bio_lines.append(line)
            if sum(len(b) for b in bio_lines) > 400:
                break

        return {
            "display_name": display_name,
            "bio": " ".join(bio_lines)[:400] or None,
            "followers": followers,
        }

    def profile_url(self, username: str) -> str:
        return f"{self.SITE_URL}/{username.strip().lstrip('@')}/"

    def hashtag_url(self, tag: str) -> str:
        return f"{self.SITE_URL}/explore/tags/{tag.strip().lstrip('#')}/"

    def username_from_url(self, href: str) -> str:
        """`/someone/` → `someone`. Anything else → "".

        Deliberately strict. Instagram's chrome is full of links that look
        like profiles — /explore/, /reels/, a post at /p/<id>/ — and a
        loose match here would fill a lead list with pages, not people.
        """
        if not href:
            return ""
        path = href.split("?")[0].split("#")[0]
        if path.startswith("http"):
            path = path.split("//", 1)[-1]
            path = path.split("/", 1)[1] if "/" in path else ""
        parts = [p for p in path.split("/") if p]
        if len(parts) != 1:
            return ""
        username = parts[0]
        if username.lower() in NOT_PROFILES or username.startswith("_u/"):
            return ""
        # Instagram handles: letters, digits, period, underscore.
        if not all(c.isalnum() or c in "._" for c in username):
            return ""
        return username
