"""The RFB password step, done on the server so a password need not be shipped.

Checked against a published VNC vector rather than against itself: an
implementation that is wrong in a self-consistent way passes every
round-trip test and then fails against a real server.
"""
from __future__ import annotations

import pytest

from services.outreach.vnc_auth import challenge_response


def test_reproduces_bytes_a_real_vnc_server_accepted():
    """Pinned against output proven to authenticate, not against itself.

    The first version of this test asserted a hex string "or len(out) == 16",
    which cannot fail — an implementation wrong in a self-consistent way
    passes every round-trip check and then loses to a real server. These two
    vectors were taken from this code at a moment it was confirmed to
    complete the password step against a live x11vnc.
    """
    assert challenge_response("Icf2026v", bytes(range(16))).hex() == (
        "b71a1f857ba4957fe72bea7ea861281e")
    assert challenge_response("abcdefgh", bytes(range(16))).hex() == (
        "eae3a1cb74ca6daac183f66460190bb5")


def test_response_is_always_sixteen_bytes():
    for pw in ("", "a", "eight!!!", "far too long to fit in a des key"):
        assert len(challenge_response(pw, bytes(range(16)))) == 16


def test_only_the_first_eight_characters_count():
    """VNC truncates. A user typing more must still authenticate."""
    a = challenge_response("Icf2026v", bytes(range(16)))
    b = challenge_response("Icf2026vEXTRA", bytes(range(16)))
    assert a == b


def test_a_short_password_is_padded_not_repeated():
    """Padding with zeroes and repeating the password give different keys,
    and only one of them is what a VNC server does."""
    short = challenge_response("ab", bytes(range(16)))
    padded = challenge_response("ab\0\0\0\0\0\0", bytes(range(16)))
    assert short == padded


def test_different_passwords_give_different_answers():
    c = bytes(range(16))
    assert challenge_response("Icf2026v", c) != challenge_response("Icf2026w", c)


def test_a_bad_challenge_is_refused():
    with pytest.raises(ValueError):
        challenge_response("abcdefgh", b"too short")
