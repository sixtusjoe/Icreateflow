"""TikTok's DM surface: the selector table, and nothing else.

Every behaviour lives in `playwright_base.PlaywrightMessenger`. What is
here is the part that is genuinely about tiktok.com — which elements to
look for, and the traps in finding them. The comments matter: most of these
entries exist because a looser version of them cost a live target.
"""
from __future__ import annotations

from typing import Any

from services.outreach.browser.playwright_base import PlaywrightMessenger

#: Ordered fallbacks — the first selector that resolves wins.
TIKTOK_SELECTORS: dict[str, Any] = {
    # Something proving the profile actually rendered, so the button checks
    # don't run against a shell that has not hydrated yet.
    "profile_loaded": (
        "[data-e2e='user-title']",
        "[data-e2e='user-subtitle']",
        "[data-e2e='followers-count']",
        "h1",
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
    "message_input": (
        "[data-e2e='message-input-area']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
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
    """TikTok. The engine, plus the table above."""

    PLATFORM = "tiktok"
    OVERLAY_DISMISS = TIKTOK_OVERLAY_DISMISS
    SELECTORS = TIKTOK_SELECTORS
    name = "playwright_tiktok"
