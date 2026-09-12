"""Screens handed out one per session.

The pool is process and filesystem heavy, so what is tested here is the
bookkeeping and the fallback — not Xvfb itself, which either exists on the
host or does not.
"""
from __future__ import annotations

import pytest

from services.outreach import display_pool


async def test_a_host_without_xvfb_gets_no_screen(monkeypatch):
    """A developer's Mac has no X server and opens real windows instead.

    Returning None rather than failing is what keeps that working.
    """
    monkeypatch.setattr(display_pool.shutil, "which", lambda _n: None)
    assert display_pool.available() is False
    assert await display_pool.acquire() is None


async def test_releasing_nothing_is_harmless():
    """Callers release in a finally, including the paths that never got one."""
    await display_pool.release(None)


def test_the_range_starts_above_the_display_it_replaces():
    """:99 was the shared one. Reusing it would put a private session back
    on the screen everybody could see."""
    assert display_pool.FIRST_DISPLAY > 99
    assert display_pool.LAST_DISPLAY >= display_pool.FIRST_DISPLAY


def test_a_display_reports_what_a_browser_needs():
    d = display_pool.Display(number=107, vnc_port=5907, xvfb=None, x11vnc=None)
    assert d.name == ":107"
    assert d.env == {"DISPLAY": ":107"}
