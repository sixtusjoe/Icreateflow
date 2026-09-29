"""Which seeds count as posts, and what a short link expands to.

The failure this pins: TikTok's own "Copy link" gives
`vt.tiktok.com/<code>`, which was not matched as a post link. The seed
fell through to the account branch, discovery went looking for the
followers of an account named after the short code, found nothing, and
reported "No profiles found. Try a broader niche, or different wording" —
advice that could never work, because the niche was not the problem.
"""
from __future__ import annotations

import pytest

from services.outreach import discovery
from services.outreach.discovery import (
    canonical_post_url, expand_short_links, post_urls_in,
)


@pytest.mark.parametrize("url", [
    "https://vt.tiktok.com/ZSbejH26F/",          # what the app hands out
    "https://vm.tiktok.com/ZSbejH26F/",          # the older short host
    "https://www.tiktok.com/t/ZSbejH26F/",
    "https://www.tiktok.com/@a/video/7639669277162769685",
    "https://www.instagram.com/p/DcskNydKfJI/",
    "https://www.instagram.com/reel/DcskNydKfJI/",
    "https://x.com/someone/status/1234567890",
])
def test_these_seeds_are_posts(url):
    assert post_urls_in([url]), f"{url} was not recognised as a post link"


@pytest.mark.parametrize("seed", [
    "https://www.tiktok.com/@someone",
    "https://www.instagram.com/someone/",
    "someaccount",
    "@someaccount",
])
def test_these_seeds_are_accounts(seed):
    assert post_urls_in([seed]) == [], f"{seed} was mistaken for a post link"


def test_an_instagram_share_link_is_rewritten_to_the_single_post():
    """The /reel/ form redirects to the scrolling feed, which has no
    comments — already documented, pinned here beside the rest."""
    assert canonical_post_url(
        "https://www.instagram.com/reel/DcskNydKfJI/?stkn=abc"
    ) == "https://www.instagram.com/p/DcskNydKfJI/"


async def test_a_short_link_that_cannot_be_resolved_is_passed_through(monkeypatch):
    """A seed is not worth failing a run over."""
    import services.outreach.discovery as discovery

    class _Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, _url): raise RuntimeError("no network")

    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **_k: _Boom())
    original = "https://vt.tiktok.com/ZSbejH26F/"
    assert await expand_short_links([original]) == [original]


async def test_a_full_url_is_left_alone(monkeypatch):
    """No request is made for a link that already names its post."""
    import services.outreach.discovery as discovery

    def _explode(**_kwargs):
        raise AssertionError("a full post URL should not be fetched")

    monkeypatch.setattr(discovery.httpx, "AsyncClient", _explode)
    url = "https://www.tiktok.com/@a/video/7639669277162769685"
    assert await expand_short_links([url]) == [url]


# --- reply threads ---------------------------------------------------------

def test_every_platform_that_can_open_replies_declares_the_reading_key():
    """`_expand_replies` reads `expand_replies`, not `comment_replies`.

    TikTok defined only the second — which is the comment *campaign's* key
    — so the harvester returned 0 on its first line and no reply thread was
    ever opened. Measured on a live video: 64 unclicked controls on a page
    whose 121 comments were 100 at the top level.
    """
    from services.outreach.browser.playwright_tiktok import PlaywrightTikTokMessenger
    from services.outreach.browser.playwright_instagram import (
        PlaywrightInstagramMessenger,
    )

    for driver in (PlaywrightTikTokMessenger, PlaywrightInstagramMessenger):
        selectors = driver.SELECTORS.get("expand_replies") or ()
        assert selectors, (
            f"{driver.name} cannot open reply threads — `_expand_replies` "
            f"returns 0 before it looks at the page"
        )


async def test_reply_reading_can_be_switched_off():
    """The checkbox has to reach the part that does the clicking."""
    from services.outreach.browser.playwright_tiktok import PlaywrightTikTokMessenger

    driver = PlaywrightTikTokMessenger.__new__(PlaywrightTikTokMessenger)
    driver._read_replies = False
    assert await PlaywrightTikTokMessenger._expand_replies(driver, page=None) == 0, (
        "switching replies off must stop before it touches the page"
    )


# --- profile links pasted as seeds --------------------------------------------

@pytest.mark.parametrize("pasted, handle", [
    ("https://x.com/allergictoguac?s=11", "allergictoguac"),
    ("https://twitter.com/someone/", "someone"),
    ("x.com/someone", "someone"),
    ("https://www.tiktok.com/@kjlyrics?is_from_webapp=1", "kjlyrics"),
    ("https://www.instagram.com/some.one/?igsh=abc", "some.one"),
    ("@plain", "plain"),
    ("plain", "plain"),
])
def test_a_pasted_profile_link_becomes_the_handle(pasted, handle):
    """Search 46 read "@https://x.com/allergictoguac?s=11" and found nobody."""
    assert discovery._seed_list(pasted) == [handle]


def test_post_links_are_left_for_the_post_reader():
    post = "https://x.com/someone/status/1234567890?s=20"
    assert discovery._seed_list(post) == [post]
    assert discovery.post_urls_in(discovery._seed_list(post)) == [post]
