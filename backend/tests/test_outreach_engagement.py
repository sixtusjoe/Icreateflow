"""Harvesting an audience from a seed's posts rather than its follower list.

A follower list is truncated hard — the same seventy to a hundred names
whether the account has 17,300 followers or 180,700 — so the people who
liked and replied to recent posts are the better source for the same
audience. These cover the parts that are ours: which links count as the
seed's own posts, and that a seed falls back rather than returning little.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.async_api", reason="playwright is not installed")

from services.outreach.browser.playwright_x import (  # noqa: E402
    PlaywrightXMessenger,
)


@pytest.fixture
def driver():
    # No browser is started; the constructor only records settings.
    return PlaywrightXMessenger(headless=True)


def test_only_the_seeds_own_posts_are_collected(driver):
    """A profile links to other people's posts as well as its own.

    Reposts, quoted replies and the sidebar all point at strangers, and
    harvesting those harvests a different audience than the one asked for.
    """
    assert driver._own_post_url("/hkuppy/status/123", "hkuppy") == (
        "https://x.com/hkuppy/status/123")
    assert driver._own_post_url("/someoneelse/status/9", "hkuppy") == ""


def test_a_handle_is_matched_regardless_of_case(driver):
    """X preserves display case in links; the seed is typed by a person."""
    assert driver._own_post_url("/Rory_Johnston/status/7", "rory_johnston")
    assert driver._own_post_url("/rory_johnston/status/7", "Rory_Johnston")


def test_photo_and_analytics_tails_are_not_posts(driver):
    """They live under the same prefix and are not separate posts — reading
    them would ask for the same audience several times over."""
    assert driver._own_post_url("/hkuppy/status/123/photo/1", "hkuppy") == ""
    assert driver._own_post_url("/hkuppy/status/123/analytics", "hkuppy") == ""


def test_a_post_with_no_author_in_the_path_is_skipped(driver):
    assert driver._own_post_url("/i/web/status/5", "hkuppy") == ""
    assert driver._own_post_url("", "hkuppy") == ""


def test_every_platform_can_be_asked_for_engagement():
    """Discovery checks for the method before using it, so a driver without
    one falls back rather than raising — but the three that matter have it."""
    from services.outreach.browser import get_driver

    for name in ("playwright_x", "playwright_tiktok", "playwright_instagram"):
        assert hasattr(get_driver(name), "discover_from_engagement"), name
        assert hasattr(get_driver(name), "recent_posts"), name
