"""Tickets for watching a sign-in browser from the page.

A ticket is the only thing standing between the public internet and a VNC
session that is driving a real browser with someone's account in it, so the
rules it has to keep are worth stating as tests rather than as comments.
"""
from __future__ import annotations

import time

import pytest

from services.outreach import session_viewer as viewer


@pytest.fixture(autouse=True)
def _clean():
    viewer.clear()
    yield
    viewer.clear()


def test_a_ticket_opens_the_account_it_was_issued_for():
    t = viewer.issue(account_id=7, user_id=1)
    assert viewer.redeem(t.value, account_id=7) is not None


def test_a_ticket_is_single_use():
    """It travels in a URL, and URLs are written down.

    Websockets cannot carry an Authorization header from a browser, so the
    ticket has to go in the query string — where it reaches history, access
    logs and referrers. Spending it once is what makes that survivable.
    """
    t = viewer.issue(account_id=7, user_id=1)
    assert viewer.redeem(t.value, account_id=7) is not None
    assert viewer.redeem(t.value, account_id=7) is None, "a ticket was reusable"


def test_a_ticket_will_not_open_a_different_account():
    """Otherwise any customer could watch any other customer sign in."""
    t = viewer.issue(account_id=7, user_id=1)
    assert viewer.redeem(t.value, account_id=8) is None


def test_a_wrong_value_is_spent_not_merely_refused():
    """A near miss must not leave the real ticket sitting there to guess at."""
    viewer.issue(account_id=7, user_id=1)
    assert viewer.redeem("not-a-real-ticket", account_id=7) is None


def test_an_expired_ticket_is_refused(monkeypatch):
    t = viewer.issue(account_id=7, user_id=1)
    monkeypatch.setattr(time, "time", lambda: t.expires_at + 1)
    assert viewer.redeem(t.value, account_id=7) is None


def test_expired_tickets_do_not_pile_up(monkeypatch):
    """Nobody spends most of these — the page opens one socket and stops."""
    first = viewer.issue(account_id=1, user_id=1)
    for n in range(2, 6):
        viewer.issue(account_id=n, user_id=1)
    assert viewer.outstanding() == 5
    monkeypatch.setattr(time, "time", lambda: first.expires_at + 1)
    assert viewer.outstanding() == 0


def test_the_vnc_target_is_localhost():
    """The port is never exposed; a ticket is the only way to reach it."""
    assert viewer.VNC_HOST in ("127.0.0.1", "::1", "localhost")


def test_a_ticket_is_not_guessable():
    values = {viewer.issue(account_id=1, user_id=1).value for _ in range(50)}
    assert len(values) == 50
    assert all(len(v) >= 32 for v in values)


def test_a_ticket_opens_only_its_own_screen():
    """The isolation is the port, not the password.

    Every visible browser used to draw on one shared display, and x11vnc
    streams a display rather than a window — so any ticket showed every
    session running on it, including someone else's login and their typing.
    A screen per session is only worth having if the ticket is bound to one.
    """
    mine = viewer.issue(account_id=7, user_id=1, vnc_port=5911)
    theirs = viewer.issue(account_id=8, user_id=2, vnc_port=5912)
    assert mine.vnc_port == 5911
    assert theirs.vnc_port == 5912
    redeemed = viewer.redeem(mine.value, account_id=7)
    assert redeemed is not None and redeemed.vnc_port == 5911


def test_a_ticket_without_a_screen_falls_back_to_the_shared_port():
    """A host with no Xvfb still has one browser on one display."""
    t = viewer.issue(account_id=7, user_id=1)
    assert t.vnc_port == viewer.VNC_PORT
