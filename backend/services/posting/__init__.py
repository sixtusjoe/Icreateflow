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
