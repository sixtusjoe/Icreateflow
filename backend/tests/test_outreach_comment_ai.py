"""Rewriting a reply so no two are the same.

TikTok hides a comment it has seen before, so a campaign posting one
line under a hundred comments is posting it to nobody. What matters as
much as the rewrite is what happens when the rewrite cannot be had: the
reply still goes out, as written.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from services.outreach import comment_ai


class _FakeDB:
    """Enough of the database for the key lookup, and nothing more."""

    def __init__(self, key=None):
        self.key = key


@pytest.fixture(autouse=True)
def no_ambient_key(monkeypatch):
    # Otherwise a developer's own key decides what these tests do.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(comment_ai.db, "get_setting",
                        lambda *a, **k: _none(), raising=False)
    monkeypatch.setattr(comment_ai.db, "get_user_settings",
                        lambda *a, **k: _empty(), raising=False)


async def _none():
    return None


async def _empty():
    return {}


def _answers(text, monkeypatch):
    async def _ask(prompt, key):
        _answers.prompt = prompt
        return text
    monkeypatch.setattr(comment_ai, "_ask", _ask)


def _has_key(monkeypatch, key="sk-test"):
    async def _api_key(database, user_id=None):
        return key
    monkeypatch.setattr(comment_ai, "_api_key", _api_key)


async def test_a_reply_is_reworded(monkeypatch):
    _has_key(monkeypatch)
    _answers("this is exactly what i needed today", monkeypatch)

    out = await comment_ai.vary(_FakeDB(), "this is what i needed")
    assert out == "this is exactly what i needed today"


async def test_no_key_posts_the_line_as_written(monkeypatch):
    """An unconfigured install still sends its campaigns."""
    async def _api_key(database, user_id=None):
        return None
    monkeypatch.setattr(comment_ai, "_api_key", _api_key)

    assert await comment_ai.vary(_FakeDB(), "nice one") == "nice one"


@pytest.mark.parametrize(
    "boom",
    [
        urllib.error.URLError("no route"),
        TimeoutError("took too long"),
        json.JSONDecodeError("bad", "", 0),
        RuntimeError("something nobody predicted"),
    ],
)
async def test_any_failure_still_posts_the_reply(monkeypatch, boom):
    """A rewrite is an improvement, never a dependency.

    The alternative is a campaign that stops when an API is slow, having
    already spent the account's attempt on the profile.
    """
    _has_key(monkeypatch)

    async def _ask(prompt, key):
        raise boom
    monkeypatch.setattr(comment_ai, "_ask", _ask)

    assert await comment_ai.vary(_FakeDB(), "love this") == "love this"


async def test_a_refusal_is_not_posted_as_a_comment(monkeypatch):
    """Posting "I can't help with that" under a video is worse than a repeat."""
    _has_key(monkeypatch)
    _answers("I can't help with rewriting promotional messages.", monkeypatch)

    assert await comment_ai.vary(_FakeDB(), "check our menu") == "check our menu"


async def test_an_answer_that_rambles_is_not_posted(monkeypatch):
    """A comment is one line. Anything much longer answered a different question."""
    _has_key(monkeypatch)
    _answers("Here are a few options you might consider: " + "word " * 80,
             monkeypatch)

    assert await comment_ai.vary(_FakeDB(), "nice") == "nice"


async def test_quotes_the_model_adds_are_stripped(monkeypatch):
    """Models wrap a rewrite in quotes however firmly they are told not to."""
    _has_key(monkeypatch)
    _answers('"needed this today"', monkeypatch)

    assert await comment_ai.vary(_FakeDB(), "needed this") == "needed this today"


async def test_what_was_already_posted_is_shown_to_the_model(monkeypatch):
    """Without it the rewrites converge — the same problem one step along."""
    _has_key(monkeypatch)
    _answers("something else entirely", monkeypatch)

    await comment_ai.vary(
        _FakeDB(), "nice one",
        avoid=["nice work", "lovely one", "great stuff"],
    )

    prompt = _answers.prompt
    assert "nice work" in prompt and "great stuff" in prompt
    assert "do not write anything close" in prompt.lower()


async def test_an_empty_line_asks_nothing_of_the_model(monkeypatch):
    called = []

    async def _ask(prompt, key):
        called.append(1)
        return "x"
    monkeypatch.setattr(comment_ai, "_ask", _ask)

    assert await comment_ai.vary(_FakeDB(), "   ") == ""
    assert not called
