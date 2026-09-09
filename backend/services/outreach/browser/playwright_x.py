"""X's DM surface: the selector table, and nothing else.

Every behaviour lives in `playwright_base.PlaywrightMessenger` — the
queueing, the retries, the delivery confirmation, follow-to-unlock, the
challenge handling. What is here is the part that is genuinely about
x.com: which elements to look for, and the traps in finding them.

**On how far these have been verified.** X serves nothing at all to a
logged-out browser. Asked for `x.com/nasa` it returned an empty body;
asked for an account that does not exist it redirected to
`/i/jf/onboarding/web?...&mode=login`. So the login-wall entries below
were measured against the live site, and everything past the wall — the
profile, the DM composer, the follow control — could not be, because
there is no signed-in X account to look through.

Those entries are built from X's own `data-testid` attributes, which are
what its web client uses for its own tests and the most stable handles it
exposes. They are a hypothesis. `scripts/verify_x_selectors.py` checks
every one of them against a real signed-in profile in about a minute, and
should be run before the first campaign — Instagram shipped with a Follow
selector that matched nothing at all, and it cost a hundred targets before
anyone looked.
"""
from __future__ import annotations

import re
from typing import Any

from services.outreach.browser.playwright_base import PlaywrightMessenger

#: Ordered fallbacks — the first selector that resolves wins.
X_SELECTORS: dict[str, Any] = {
    # Something proving the profile rendered, so the button checks below do
    # not run against a shell that has not hydrated. X renders the whole
    # page client-side, so this matters more here than elsewhere.
    "profile_loaded": (
        "[data-testid='UserName']",
        "[data-testid='UserProfileHeader_Items']",
        "[data-testid='primaryColumn']",
    ),
    "profile_missing": (
        "[data-testid='emptyState']",
        "text=This account doesn’t exist",
        "text=This account doesn't exist",
        "text=Account suspended",
        "text=Caution: This account is temporarily restricted",
    ),
    # Verified against the live site: logged out, every URL — profile,
    # missing profile, anything — lands on this flow. It is the one part of
    # this table that has been seen rather than inferred.
    "login_wall": (
        "[data-testid='loginButton']",
        "[data-testid='google_sign_in_container']",
        "text=Sign in to X",
        "text=See what’s happening",
        "text=See what's happening",
        "text=Select an option below",
    ),
    # Tiered, most specific first. X's own test id is unambiguous and comes
    # first; the fallbacks exist for the day it is renamed.
    #
    # The generic tier deliberately does not say `:has-text('Message')`.
    # X's left navigation has a "Messages" entry, and `_first_visible`
    # races the selectors inside a tier, so a substring match on that word
    # can win over the profile's own control and navigate to the inbox.
    # This is not hypothetical — it is exactly how TikTok and Instagram
    # both lost targets.
    "message_button": (
        ("[data-testid='sendDMFromProfile']",),
        (
            "[aria-label^='Message @']",
            "div[role='button'][aria-label^='Message']",
        ),
    ),
    # The DM composer. X wraps a contenteditable in a labelled container;
    # the inner editable is what accepts typing.
    "message_input": (
        "[data-testid='dmComposerTextInput'] div[contenteditable='true']",
        "[data-testid='dmComposerTextInput']",
        "div[data-testid='dmComposerTextInput'][contenteditable='true']",
        "div[role='textbox'][contenteditable='true']",
    ),
    # The inbox with no conversation open — clicking Message landed on the
    # messages app instead of opening a thread, so there is nothing to type
    # into and the engine goes looking for the target's own conversation.
    "messages_view": (
        "[data-testid='DmActivityViewport']",
        "[aria-label='Timeline: Messages']",
        "[data-testid='conversation']",
    ),
    "send_button": (
        "[data-testid='dmComposerSendButton']",
        "div[role='button'][aria-label='Send']",
    ),
    # A message that is in the thread. `messageEntry` is the row X gives
    # each one; the scroller is the fallback for reading the whole thread.
    "sent_confirmation": (
        "[data-testid='messageEntry']",
        "[data-testid='DmScrollerContainer'] [data-testid='tweetText']",
        "[data-testid='DmScrollerContainer'] div[role='row']",
    ),
    # X's Follow control carries the account's numeric id in its test id —
    # `data-testid="1234567-follow"` — and flips to `-unfollow` once you
    # follow. The suffix match is the whole point.
    #
    # The generic tier is `:has(span:text-is('Follow'))`, not
    # `:text-is('Follow')` and emphatically not `:has-text('Follow')`.
    # Both of those were wrong on Instagram, in opposite directions:
    # `:text-is` matches the smallest element holding the text, which is
    # the inner span rather than the button, so it matched nothing at all;
    # `:has-text` is a substring, so on a profile you already follow it
    # matches the *Following* button and unfollows them. Exact text on a
    # descendant is the pair that works.
    "follow_button": (
        ("[data-testid$='-follow']",),
        (
            "div[role='button']:has(span:text-is('Follow'))",
            "button:has(span:text-is('Follow'))",
        ),
    ),
    "already_following": (
        "[data-testid$='-unfollow']",
        "div[role='button']:has(span:text-is('Following'))",
        "button:has(span:text-is('Following'))",
    ),
    # A protected account: the request is sent and waits for a person.
    # Kept apart from "Following" because it means something different —
    # nothing can be sent until it is accepted.
    "follow_requested": (
        "div[role='button']:has(span:text-is('Pending'))",
        "button:has(span:text-is('Pending'))",
    ),
    # Refused by the recipient rather than by X: their settings, not our
    # account's standing. Filed as `messaging_unavailable` so it does not
    # count against the sending account's error budget.
    "recipient_refused": (
        "text=You can’t send messages to this account",
        "text=You can't send messages to this account",
        "text=doesn’t allow direct messages",
        "text=doesn't allow direct messages",
        "text=Only people they follow can send",
    ),
    # Refused by the platform. The message may sit in the thread looking
    # delivered while this says otherwise — which is why it is judged
    # before the delivery check, not after.
    "message_refused": (
        "text=Your message wasn’t sent",
        "text=Your message wasn't sent",
        "text=Message not sent",
        "text=Something went wrong. Your message was not sent",
    ),
    "rate_limited": (
        "text=You are over the daily limit for sending Direct Messages",
        "text=You have exceeded the number of allowed attempts",
        "text=Rate limit exceeded",
        "text=Try again later",
    ),
    # X's identity check. A person has to clear it; the engine holds the
    # browser open while it is on screen rather than blaming the target.
    # The Arkose puzzle arrives in an iframe, so the frame is matched too.
    "verification_challenge": (
        "iframe[src*='arkoselabs']",
        "iframe[title*='challenge']",
        "text=Verify your identity",
        "text=We need to make sure you're a real person",
        "text=Confirm your identity",
        "text=unusual login activity",
    ),
    "site_error": (
        "text=Something went wrong. Try reloading.",
        "text=Try reloading",
        "text=Oops, something went wrong",
    ),
    # X's DM composer takes media through a hidden file input behind the
    # image icon. Clicking the icon opens an OS picker no automation can
    # reach; setting the input is the only route in.
    "attach_image": (
        "[data-testid='dmComposerTextInput'] ~ * input[type='file']",
        "input[data-testid='fileInput']",
        "input[type='file'][accept*='image']",
    ),

    # --- discovery ---------------------------------------------------------
    # Unlike Instagram, X's followers list is a real page with its own URL,
    # so it does not have to be opened by clicking a modal into existence.
    # The link is still matched, because the engine clicks it when it is
    # already on the profile.
    "followers_link": (
        "a[href$='/followers']",
        "a[href$='/verified_followers']",
    ),
    # The followers list is the main timeline, not a dialog — the page
    # itself scrolls, so the pointer goes over the primary column.
    "scroll_container": (
        "[data-testid='primaryColumn']",
        "main",
    ),
    # People, in a list of people: X's user cell.
    "liker": (
        "[data-testid='UserCell'] a[href^='/']",
        "[data-testid='cellInnerDiv'] a[role='link'][href^='/']",
    ),
    "post_link": (
        "a[href*='/status/']",
    ),
    # The author and everyone in a post's replies.
    "post_people": (
        "[data-testid='User-Name'] a[href^='/']",
        "[data-testid='UserCell'] a[href^='/']",
    ),
    "search_input": (
        "[data-testid='SearchBox_Search_Input']",
        "input[placeholder='Search']",
    ),
    "search_result": (
        "[data-testid='UserCell']",
        "[data-testid='typeaheadResult']",
    ),
    # X pages by infinite scroll; there is no "load more" control to press.
    "load_more": (),
}


#: X's consent and interstitial furniture. The generic list covers the
#: cookie banners; these are the ones X puts in the way of a profile.
X_OVERLAY_DISMISS = (
    "[data-testid='xMigrationBottomBar']",
    "[data-testid='sheetDialog'] [aria-label='Close']",
    "div[role='button'][aria-label='Close']",
) + PlaywrightMessenger.OVERLAY_DISMISS


#: x.com paths that are not profiles. A link to /home or /i/flow is not a
#: lead, and treating one as a handle would put nonsense in the list.
NOT_PROFILES = {
    "i", "home", "explore", "notifications", "messages", "settings", "compose",
    "search", "hashtag", "intent", "login", "signup", "logout", "tos", "privacy",
    "about", "status", "share", "download", "account", "session", "help",
    "explore_locations", "topics", "lists", "communities", "premium_sign_up",
    "jobs", "bookmarks", "verified_followers", "followers", "following",
}

#: X handles: 1-15 of letters, digits and underscore. Nothing else, ever —
#: which makes this a much tighter net than Instagram's.
_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_IS_STAT = re.compile(r"^[\d.,]+\s*[KkMm]?\s+(Following|Followers|Posts)$")


class PlaywrightXMessenger(PlaywrightMessenger):
    """X (formerly Twitter). The engine, plus the table above."""

    PLATFORM = "x"
    SELECTORS = X_SELECTORS
    OVERLAY_DISMISS = X_OVERLAY_DISMISS
    CHALLENGE_FRAME_HINTS = ("arkoselabs", "challenge", "funcaptcha")
    # X's followers list is an ordinary page with its own URL — verified
    # live: x.com/<handle>/followers rendered 35 UserCells and contained no
    # dialog at all. Instagram's is a modal, and the engine assumed every
    # platform's was, so the harvest clicked a link, found no dialog and
    # scrolled nothing while reporting zero found and no error.
    FOLLOWERS_IN_DIALOG = False
    SITE_URL = "https://x.com"
    SEARCH_URL = "https://x.com/explore"
    SEARCH_QUERY_URL = "https://x.com/search?q={q}&f=user"
    name = "playwright_x"

    async def profile_summary(self, page, username: str) -> dict[str, Any]:
        """Read a profile from the text of the page.

        Same approach as Instagram's, for the same reason: X's header is a
        pile of generated class names, and its structured shape changes
        more often than the order the text appears in. That order is:

            Display Name / @handle / bio… / Joined … / N Following /
            N Followers

        so it is parsed rather than queried. The bio is whatever sits
        between the handle and the join date.
        """
        empty = {"display_name": None, "bio": None, "followers": None}
        try:
            await page.goto(self.profile_url(username), wait_until="domcontentloaded",
                            timeout=self._timeout)
            await self._dismiss_overlays(page)
            await page.wait_for_timeout(2500)
            text_content = await page.inner_text("[data-testid='primaryColumn']")
        except Exception as exc:  # noqa: BLE001 — one bad profile is not fatal
            print(f"[discovery] profile @{username} failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return empty

        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
        if not lines:
            return empty

        followers = None
        match = re.search(r"([\d.,]+\s*[KkMm]?)\s+Followers", text_content, re.I)
        if match:
            followers = _as_int(match.group(1))

        handle = f"@{username.lstrip('@')}".lower()
        display_name = None
        for line in lines:
            if line.lower() == handle:
                break
            if not _IS_STAT.match(line) and line not in ("Follow", "Following", "Message"):
                display_name = line[:120]
                break

        bio_lines: list[str] = []
        started = False
        for line in lines:
            if not started:
                started = line.lower() == handle
                continue
            if line.startswith("Joined ") or _IS_STAT.match(line):
                break
            if line in ("Follow", "Following", "Message", "Pending", "Subscribe"):
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
        return f"{self.SITE_URL}/{username.strip().lstrip('@')}"

    def followers_urls(self, username: str) -> tuple[str, ...]:
        """Verified Followers first, then Followers.

        X splits a profile's followers across tabs, and they are separate
        pages rather than a filter over one list — so harvesting only
        `/followers` drops every verified account that follows them.
        Verified first because it is the shorter list and the one more
        likely to be worth reading if a run is cut short.

        `/following` is deliberately not here: those are accounts this
        person follows, which is a different audience and not what was
        asked for.
        """
        base = self.profile_url(username)
        return (f"{base}/verified_followers", f"{base}/followers")

    def hashtag_url(self, tag: str) -> str:
        return f"{self.SITE_URL}/hashtag/{tag.strip().lstrip('#')}"

    def username_from_url(self, href: str) -> str:
        """`/someone` → `someone`. Anything else → "".

        Deliberately strict. X's chrome is full of links that look like
        profiles — /home, /explore, /i/flow/login, a post at
        /someone/status/123 — and a loose match here would fill a lead list
        with pages rather than people. A handle is one path segment and
        nothing more.
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
        if username.lower() in NOT_PROFILES:
            return ""
        if not _HANDLE.match(username):
            return ""
        return username


def _as_int(raw: str) -> int | None:
    """"1.2K" → 1200. X abbreviates every count over a thousand."""
    text = (raw or "").strip().replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text[-1] in "Kk":
        multiplier, text = 1_000, text[:-1]
    elif text[-1] in "Mm":
        multiplier, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None
