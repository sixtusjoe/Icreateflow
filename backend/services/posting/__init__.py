"""Platform posting adapters for the Clipping pipeline.

Each adapter module exports two async functions with the shared signature:

    async def upload_video(
        access_token: str,
        video_source: str,          # local filesystem path OR a public URL
        caption: str,
        **kwargs,
    ) -> dict                        # {"platform_post_id": str, "permalink": str|None}

    async def get_view_count(access_token: str, platform_post_id: str) -> int

Adapters raise `PostingError` on failure. The scheduler catches and records the
error on the `clip_posts` row.
"""


class PostingError(Exception):
    """Raised by a platform adapter when a post/view call fails."""


class PostDeletedError(PostingError):
    """Raised by `get_view_count` when the platform reports the post as gone
    (404, "Object with ID does not exist", empty items, etc). Subclasses
    PostingError so existing catch-all handlers still work, but lets the
    poller specifically mark the row as deleted_at instead of just logging.
    """


class YouTubeQuotaExhausted(PostingError):
    """Raised by the YouTube adapter when the Data API returns 403 with a
    `quotaExceeded` reason. Distinct from PostingError so the view poller
    can short-circuit the entire YouTube branch (skip the batch AND the
    per-row fallback) until the daily quota resets at midnight Pacific —
    avoiding the 100+ identical 403 entries that flooded the error log.
    """


class TikTokCreatorBlocked(PostingError):
    """Raised when `creator_info/query` reports the creator can't post right
    now (cooldown, rate-limit, account in violation, etc.). Distinct from
    PostingError so the UI can render a clear "try again later" message and
    block the post-to-TikTok flow per TikTok's required UX rule.
    """
