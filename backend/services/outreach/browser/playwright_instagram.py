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

from typing import Any

from services.outreach.browser.playwright_base import PlaywrightMessenger

#: Ordered fallbacks — the first selector that resolves wins.
INSTAGRAM_SELECTORS: dict[str, Any] = {
    # Something proving the profile rendered, so the checks below are not
    # racing an empty shell.
    "profile_loaded": (
        "header section",
        "main header",
        "h2",
        "h1",
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
    "follow_button": (
        ("button:text-is('Follow')",),
        (
            "div[role='button']:text-is('Follow')",
            "[role='button']:text-is('Follow')",
        ),
    ),
    "already_following": (
        "button:text-is('Following')",
        "button:text-is('Requested')",
        "div[role='button']:text-is('Following')",
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
