"""Every TikTok URL this reader uses, written down verbatim.

Recorded 2026-09-22 from a real logged-in session with the page's own
requests, not guessed. The findings behind these are in
BROWSERLESS-HANDOFF.md §2a.
"""
from __future__ import annotations

HOST = "https://www.tiktok.com"

#: A post's top-level comments. Cursor-paged: `cursor` advances by `count`.
#: Response carries `comments`, `cursor`, `has_more`, `total`.
COMMENT_LIST = f"{HOST}/api/comment/list/"

#: The replies under one comment, keyed by `comment_id` + `item_id`.
#: Most of a big post's people are here rather than in the root list — the
#: root list stops at a cap (see COMMENT_ROOT_CAP), and 191 of one post's
#: 619 root comments carried 441 more people between them.
COMMENT_REPLY_LIST = f"{HOST}/api/comment/list/reply/"

#: The root list stops returning at this cursor with `has_more=0`, which is
#: a platform cap and *not* the end of the comments. Measured on a post
#: whose stated total was 1,637: the root list ended at 1000.
#:
#: It is written down because `has_more=0` at exactly 1000 looks like a
#: clean finish, and a reader that reports "complete" there is wrong in a
#: way nothing downstream can detect.
COMMENT_ROOT_CAP = 1000

#: What the page asks for per request. Kept the same as the real client's:
#: a larger page is the sort of difference that is cheap for them to notice
#: and worth nothing to us.
PAGE_SIZE = 20

#: Signing parameters, as of 2026-09-22. `X-Bogus` is now the literal "1"
#: and carries nothing; the live pair is `X-Gnarly` and `X-Dynosaur`. These
#: names rotate — the reader never constructs them, it copies whatever the
#: browser's own request used, so a rename costs nothing here.
SIGNING_PARAMS = ("X-Bogus", "X-Gnarly", "X-Dynosaur", "msToken")

#: Query keys the reader sets itself; everything else is copied from the
#: minted request untouched.
CURSOR = "cursor"
COUNT = "count"
AWEME_ID = "aweme_id"
ITEM_ID = "item_id"
COMMENT_ID = "comment_id"


def post_id_from_url(url: str) -> str | None:
    """The numeric id in `.../@handle/video/7684154011863371021?...`."""
    if not url:
        return None
    cleaned = url.split("?", 1)[0].rstrip("/")
    tail = cleaned.rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


def profile_url(username: str) -> str:
    return f"{HOST}/@{str(username).lstrip('@')}"
