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
    # The DM composer.
    #
    # Measured against the live site: X's current chat UI names everything
    # `dm-*` in kebab-case, and the input is a real <textarea> — not the
    # camelCase `dmComposerTextInput` contenteditable the older interface
    # used. The old names are kept behind the new ones because not every
    # account is on the new UI yet.
    #
    # It is also slow: the composer was absent seven seconds after the
    # click and present a few seconds later, which is what "the composer
    # never opened" meant on the first live send.
    "message_input": (
        "textarea[data-testid='dm-composer-textarea']",
        "[data-testid='dm-composer-input-container'] textarea",
        "[data-testid='dm-composer-form'] textarea",
        "[data-testid='dmComposerTextInput'] div[contenteditable='true']",
        "[data-testid='dmComposerTextInput']",
        "div[role='textbox'][contenteditable='true']",
    ),
    # The inbox with no conversation open — clicking Message landed on the
    # messages app instead of opening a thread, so there is nothing to type
    # into and the engine goes looking for the target's own conversation.
    "messages_view": (
        "[data-testid='dm-inbox-panel']",
        "[data-testid='dm-empty-conversation-state']",
        "[data-testid='DmActivityViewport']",
        "[aria-label='Timeline: Messages']",
    ),
    # Not seen on an empty composer — X appears to reveal it once there is
    # something to send. The engine presses Enter when it cannot find a
    # send control, which is what a person does here anyway, and the
    # delivery check decides whether that worked.
    "send_button": (
        "[data-testid='dm-composer-send-button']",
        "[data-testid='dm-composer-form'] button[type='submit']",
        "[data-testid='dmComposerSendButton']",
        "div[role='button'][aria-label='Send']",
    ),
    # A message that is in the thread. `messageEntry` is the row X gives
    # each one; the scroller is the fallback for reading the whole thread.
    # A message that is in the thread. `dm-message-list` is confirmed
    # present in the new UI; the row inside it could not be read, because
    # every existing conversation on the test account sits behind the chat
    # PIN. So the list itself is matched and its text searched, which is
    # what the delivery check does with whatever it is given.
    "sent_confirmation": (
        "[data-testid='dm-message-list']",
        "[data-testid='dm-message-scroller']",
        "[data-testid='messageEntry']",
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
    # Read-only. X puts a banner where the composer goes: "This
    # conversation is currently in read-only mode." Seen live on
    # @joshyoung — the send button had nothing to click, and the job spent
    # ninety-five seconds finding that out and then trying to confirm a
    # delivery that never happened.
    "x_read_only": (
        "text=currently in read-only mode",
        "text=read-only mode",
    ),
    # A closed inbox: nothing was sent, and nothing will be.
    #
    # X's words, from a live send: "@trend_bullish has a closed inbox. If
    # you know their X Number you can still message them", with "Not Now"
    # and "Use X Number" in place of the composer. The thread was empty —
    # this one blocks the send outright, unlike the notice below, where the
    # message goes into the thread and only its routing is in question.
    "x_inbox_closed": (
        "text=has a closed inbox",
        "div[role='button']:has-text('Use X Number')",
    ),
    # NOT a block, despite how it reads. X shows this beside a message it
    # has already delivered: "@name doesn't follow you. If you know their X
    # Number you can reach their inbox directly", with an "Enter X Number"
    # button — and the composer still there beneath it.
    #
    # Verified on a live send to @cherykang: the message was in the thread
    # at 8:03, the conversation list read "You: Hello", and this notice was
    # on screen the whole time. It is X offering an *additional* route to
    # the inbox, not refusing the one that was used — the message goes to
    # their requests.
    #
    # It was briefly treated as a recipient block, which marked delivered
    # messages as failures and left them queued to be sent again. Kept as a
    # selector so the send can say where the message landed, and
    # deliberately absent from RECIPIENT_BLOCKS.
    "delivered_note": (
        "text=If you know their X Number",
    ),
    "x_number_required": (
        "text=If you know their X Number",
        "text=doesn’t follow you",
        "text=doesn't follow you",
        "[data-testid='dm-x-number-button']",
        "div[role='button']:has-text('Enter X Number')",
    ),
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
        # The one that matters most now that the reload check is gone.
        #
        # X draws the message into the thread, lists it in the sidebar as
        # "You: Hello", and then marks the bubble "Failed, Try Again" in
        # red. Every other signal says delivered; only this says otherwise.
        # Seen live on @gugo907 at 8:36.
        #
        # Without it, confirming a send from the thread alone would report
        # a failed message as delivered — which is the exact class of lie
        # the delivery check exists to prevent, arrived at from the
        # opposite direction.
        "text=Failed, Try Again",
        "text=Failed, try again",
        "[data-testid='dm-message-failed']",
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
        # X Chat's encryption passcode. Not a puzzle, but the same
        # situation as far as the engine is concerned: a person has to type
        # something before anything can proceed, and no amount of retrying
        # substitutes. Seen live on the reload after a send — the thread is
        # not shown to anyone who cannot supply the code.
        #
        # Without this the passcode screen reads as "this profile has no
        # Message button", and writes off a reachable target.
        "[data-testid='pin-code-input-container']",
        "[data-testid='pin-title']",
        "text=Enter Passcode",
        "text=Your passcode is required to recover your encryption keys",
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
        "input[data-testid='dm-composer-file-input']",
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
    # People, in a list of people: X's user cell — but only the ones in
    # the column being read.
    #
    # X puts a "Who to follow" module in the right sidebar, built from the
    # same UserCell, so an unscoped match harvests strangers X is
    # recommending alongside the followers actually asked for. Measured: an
    # account with 281 followers yielded 298 names, and the surplus was the
    # sidebar.
    "liker": (
        "[data-testid='primaryColumn'] [data-testid='UserCell'] a[href^='/']",
        "[data-testid='primaryColumn'] [data-testid='cellInnerDiv'] "
        "a[role='link'][href^='/']",
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
    # The chat UI builds the whole conversation client-side after the
    # click. Measured: no composer seven seconds in, one a few seconds
    # later. The shared fifteen-second budget was the difference between
    # a send and "the composer never opened".
    COMPOSER_TIMEOUT_MS = 30000
    # X routes a stranger's DM away from the inbox, so every target is
    # followed before it is messaged rather than only the ones that turn
    # out to have no Message button.
    FOLLOW_BEFORE_MESSAGE = True
    # Reloading an X chat does not show the conversation again. Measured
    # across a live run: ten targets whose message was in the thread and
    # whose conversation list read "You: Hello" were all recorded as
    # failures by the reload check. The recipient blocks above are what
    # separate a real non-send from a delivery here.
    CONFIRM_BY_RELOAD = False
    # Most specific first — "doesn't follow you" is a handshake X wants,
    # not a restriction the recipient set.
    RECIPIENT_BLOCKS = (
        (
            "x_read_only",
            "has a read-only conversation on X — the composer is replaced by "
            "a banner, so nothing was sent and nothing can be",
        ),
        (
            "x_inbox_closed",
            "has a closed inbox on X, so the message was never sent — only "
            "their X Number would reach them, and this worker does not have "
            "it",
        ),
        (
            "recipient_refused",
            "does not accept message requests from this account",
        ),
    )
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

    async def _profile_follow_control(self, page):
        """The profile's own Follow button — never a suggestion's.

        Every X profile carries three to six *other* follow buttons, built
        from the same markup as the real one: the "Who to follow" module in
        the sidebar and inline in the timeline. Measured on three profiles:
        3, 6 and 6 buttons, every one of them a suggestion.

        A selector cannot tell them apart, because the difference is an
        ancestor — suggestions sit inside a `UserCell`, the profile's own
        control sits in the header wrapped in `placementTracking`. So the
        page is asked directly, and the answer is tagged with an attribute
        so the ordinary click path can use it.

        This was not academic. Unscoped, the driver clicked whichever came
        first in the DOM — a stranger from the sidebar — on every target.
        The account followed about seventy accounts that were never on the
        list, and every real target came back "refused" because its button
        never changed. It looked exactly like a rate limit, and was
        explained away as one twice.
        """
        testid = await page.evaluate("""() => {
            document.querySelectorAll('[data-icf-own-follow]').forEach(
                el => el.removeAttribute('data-icf-own-follow'));
            const all = Array.from(document.querySelectorAll(
                "[data-testid$='-follow'], [data-testid$='-unfollow']"));
            const own = all.filter(el =>
                !el.closest("[data-testid='UserCell']") &&
                !el.closest("[data-testid='sidebarColumn']"));
            if (!own.length) return null;
            // The header sits above everything else on the page.
            own.sort((a, b) =>
                a.getBoundingClientRect().top - b.getBoundingClientRect().top);
            const el = own[0];
            el.setAttribute('data-icf-own-follow', '1');
            return el.getAttribute('data-testid') || '';
        }""")
        if not testid:
            return None, None

        locator = page.locator("[data-icf-own-follow='1']").first
        if testid.endswith("-unfollow"):
            return "following", locator
        try:
            label = ((await locator.inner_text(timeout=1000)) or "").strip().lower()
        except Exception:  # noqa: BLE001 — the label is a refinement, not the answer
            label = ""
        if "pending" in label or "requested" in label:
            return "pending", locator
        return "can_follow", locator

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
