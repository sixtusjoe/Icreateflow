"""Mass commenting: the video, the lines, and the slots that carry them.

Nothing here touches a browser. What it covers is the part that decides
what gets posted and how many times — which is where a comment campaign
can go wrong quietly, by posting one sentence twenty times or by posting
nothing at all.
"""
from __future__ import annotations

import json
import random

import pytest

from services.outreach import comments
from services.outreach.constants import ACTIVITY_COMMENT, ACTIVITY_MESSAGE


def test_variations_come_back_in_the_order_given():
    campaign = {"comment_variations": json.dumps(["first", "second", "third"])}
    assert comments.variations(campaign) == ["first", "second", "third"]


def test_blank_lines_are_not_comments():
    """An editor's trailing newline must not become a comment that says nothing."""
    campaign = {"comment_variations": json.dumps(["real", "   ", "", "also real"])}
    assert comments.variations(campaign) == ["real", "also real"]


def test_a_campaign_with_no_variations_falls_back_to_the_message_box():
    """A campaign written before variations existed still has something to say."""
    campaign = {"comment_variations": None, "message_template": "nice one\nlove this"}
    assert comments.variations(campaign) == ["nice one", "love this"]


def test_unreadable_variations_do_not_take_the_campaign_down():
    campaign = {"comment_variations": "{not json", "message_template": "fallback"}
    assert comments.variations(campaign) == ["fallback"]


def test_picking_uses_the_whole_list():
    """Every line must be reachable, or the extras are decoration.

    The point of variations is that one video does not collect the same
    sentence from every account; a picker that favours one line defeats it.
    """
    lines = ["a", "b", "c", "d"]
    rng = random.Random(12345)
    seen = {comments.pick(lines, rng) for _ in range(200)}
    assert seen == set(lines)


def test_picking_nothing_is_an_error_not_an_empty_comment():
    with pytest.raises(comments.CommentSetupError):
        comments.pick([])


@pytest.mark.parametrize(
    "campaign, because",
    [
        ({"target_url": "", "comment_count": 5,
          "comment_variations": json.dumps(["hi"])}, "no video"),
        ({"target_url": "https://www.tiktok.com/@a/video/1", "comment_count": 0,
          "comment_variations": json.dumps(["hi"])}, "no count"),
        ({"target_url": "https://www.tiktok.com/@a/video/1",
          "comment_count": comments.MAX_COMMENTS + 1,
          "comment_variations": json.dumps(["hi"])}, "over the ceiling"),
        ({"target_url": "https://www.tiktok.com/@a/video/1", "comment_count": 5,
          "comment_variations": json.dumps([])}, "nothing to say"),
    ],
)
def test_a_campaign_that_cannot_comment_is_refused(campaign, because):
    with pytest.raises(comments.CommentSetupError):
        comments.validate(campaign)


def test_a_workable_campaign_is_accepted():
    comments.validate({
        "target_url": "https://www.tiktok.com/@a/video/1",
        "comment_count": 3,
        "comment_variations": json.dumps(["nice", "love this"]),
    })


def test_only_comment_campaigns_are_treated_as_one():
    assert comments.is_comment({"activity": ACTIVITY_COMMENT})
    assert not comments.is_comment({"activity": ACTIVITY_MESSAGE})
    assert not comments.is_comment({})  # no activity means the default


# --- what the client is handed --------------------------------------------
#
# The column holds JSON. The page renders the lines with .join(), so a
# string arriving where a list belongs is not a cosmetic mismatch — it
# takes the page down with "lines.join is not a function".


@pytest.mark.parametrize(
    "stored, expected",
    [
        ('["nice", "love this"]', ["nice", "love this"]),
        ("[]", []),
        (None, []),
        ("not json at all", []),
        ('{"not": "a list"}', []),
        (["already", "a list"], ["already", "a list"]),
    ],
)
def test_variations_always_reach_the_client_as_a_list(stored, expected):
    import routers.outreach as outreach_router

    out = outreach_router._campaign_public(
        {
            "id": 1,
            "comment_variations": stored,
            "total_targets": 0,
            "processed_count": 0,
            "attachment_path": None,
        }
    )
    assert out["comment_variations"] == expected
    assert isinstance(out["comment_variations"], list)
