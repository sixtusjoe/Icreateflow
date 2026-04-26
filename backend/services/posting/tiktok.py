"""TikTok Content Posting API v2 adapter."""
from __future__ import annotations

import asyncio
import httpx

from . import PostingError, PostDeletedError


API_BASE = "https://open.tiktokapis.com/v2"


async def upload_video(access_token: str, video_source: str, caption: str, **kwargs) -> dict:
    """Publish a video to TikTok via the PULL_FROM_URL flow.

    `video_source` must be a publicly-reachable URL (e.g. a Drive direct-download
    link). Local uploads are not supported by this adapter in v1.

    Pass `privacy_level` via kwargs to override the default. While a TikTok app
    is unaudited, PUBLIC_TO_EVERYONE is rejected — only SELF_ONLY is allowed.
    """
    if not video_source.startswith("http"):
        raise PostingError("TikTok adapter only supports URL video sources in v1")

    privacy_level = kwargs.get("privacy_level") or "SELF_ONLY"
    init_body = {
        "post_info": {"title": (caption or "")[:2200], "privacy_level": privacy_level},
        "source_info": {"source": "PULL_FROM_URL", "video_url": video_source},
    }
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{API_BASE}/post/publish/video/init/", json=init_body, headers=headers
        )
        if r.status_code >= 400:
            raise PostingError(f"TikTok init failed {r.status_code}: {r.text[:200]}")
        data = r.json().get("data") or {}
        publish_id = data.get("publish_id")
        if not publish_id:
            raise PostingError(f"TikTok init missing publish_id: {r.text[:200]}")

        # Poll for status (up to ~3 min)
        for _ in range(36):
            await asyncio.sleep(5)
            s = await client.post(
                f"{API_BASE}/post/publish/status/fetch/",
                json={"publish_id": publish_id},
                headers=headers,
            )
            sd = (s.json().get("data") or {}) if s.status_code < 400 else {}
            status = sd.get("status")
            if status == "PUBLISH_COMPLETE":
                video_id = (sd.get("publicly_available_post_id") or [None])[0]
                return {
                    "platform_post_id": str(video_id or publish_id),
                    "permalink": None,
                }
            if status in ("FAILED", "EXPIRED"):
                raise PostingError(f"TikTok publish failed: {sd}")
        raise PostingError("TikTok publish timed out")


async def upload_photo_slideshow(
    access_token: str,
    photo_urls: list[str],
    caption: str,
    privacy_level: str = "SELF_ONLY",
    auto_add_music: bool = True,
    **kwargs,
) -> dict:
    """Publish a swipeable photo slideshow via TikTok's content/init endpoint.

    `photo_urls` must all be publicly-reachable HTTPS URLs. TikTok will pull
    each image and stitch them into a slideshow post. Stats are queried via
    the same /v2/video/query/ endpoint as videos (slideshows share the ID space).
    """
    if not photo_urls:
        raise PostingError("TikTok slideshow needs at least one photo URL")
    for u in photo_urls:
        if not u.startswith("http"):
            raise PostingError("TikTok slideshow requires public URLs, not local paths")

    # TikTok renders both `title` and `description` on slideshows — putting the
    # caption in both duplicates it. Leave title empty; use description only.
    init_body = {
        "post_info": {
            "title": "",
            "description": (caption or "")[:4000],
            "privacy_level": privacy_level,
            "disable_comment": False,
            "auto_add_music": auto_add_music,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": photo_urls,
        },
        "post_mode": "DIRECT_POST",
        "media_type": "PHOTO",
    }
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{API_BASE}/post/publish/content/init/", json=init_body, headers=headers
        )
        if r.status_code >= 400:
            raise PostingError(f"TikTok slideshow init failed {r.status_code}: {r.text[:300]}")
        data = r.json().get("data") or {}
        publish_id = data.get("publish_id")
        if not publish_id:
            raise PostingError(f"TikTok slideshow init missing publish_id: {r.text[:200]}")

        for _ in range(36):
            await asyncio.sleep(5)
            s = await client.post(
                f"{API_BASE}/post/publish/status/fetch/",
                json={"publish_id": publish_id},
                headers=headers,
            )
            sd = (s.json().get("data") or {}) if s.status_code < 400 else {}
            status = sd.get("status")
            if status == "PUBLISH_COMPLETE":
                post_id = (sd.get("publicly_available_post_id") or [None])[0]
                return {
                    "platform_post_id": str(post_id or publish_id),
                    "permalink": None,
                }
            if status in ("FAILED", "EXPIRED"):
                raise PostingError(f"TikTok slideshow publish failed: {sd}")
        raise PostingError("TikTok slideshow publish timed out")


class TikTokStatsUnavailable(PostingError):
    """Raised when per-video stats can't be fetched for scope reasons.

    The Content Posting API scopes (`video.publish`, `video.upload`) do NOT
    grant access to /v2/video/query/ — that needs `video.list` from the
    Display API, which requires a separate TikTok developer-portal approval.
    The poller treats this as a "skip silently" signal instead of an error.
    """


def _is_publish_id(raw: str) -> bool:
    """TikTok publish_ids look like ``v_pub_url~v2-1.<digits>`` — not a video_id."""
    return bool(raw) and raw.strip().startswith("v_pub_url~")


async def _fetch_publicly_available_post_id(
    client: httpx.AsyncClient, access_token: str, publish_id: str
) -> str | None:
    """Ask /post/publish/status/fetch/ if the publish_id now has a public video id."""
    try:
        r = await client.post(
            f"{API_BASE}/post/publish/status/fetch/",
            json={"publish_id": publish_id},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            return None
        sd = (r.json().get("data") or {})
        vid = (sd.get("publicly_available_post_id") or [None])[0]
        return str(vid) if vid else None
    except Exception:
        return None


async def _list_videos(
    client: httpx.AsyncClient, access_token: str, max_count: int = 20
) -> list[dict]:
    """Return the authed user's most recent videos via /video/list/."""
    try:
        r = await client.post(
            f"{API_BASE}/video/list/?fields=id,create_time,view_count,share_url",
            json={"max_count": max_count},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            return []
        return ((r.json().get("data") or {}).get("videos")) or []
    except Exception:
        return []


async def resolve_video_id(
    access_token: str,
    stored_id: str,
    posted_at_epoch: int | None = None,
) -> str | None:
    """Upgrade a stored publish_id to a real video_id.

    TikTok's /post/publish/video/init/ returns a ``publish_id`` like
    ``v_pub_url~v2-1.<digits>`` that's only usable against
    /post/publish/status/fetch/. The real public video_id is a separate
    integer that only materialises after moderation — and for SELF_ONLY
    posts, /status/fetch/ never returns it at all.

    Strategy:
      1. If stored_id is already a bare integer, return it unchanged.
      2. Call /post/publish/status/fetch/ — returns publicly_available_post_id
         once the post has moderated to a public state.
      3. Fall back to /video/list/ (requires the ``video.list`` scope) and
         match by create_time closest to posted_at_epoch, else take the
         newest. Videos posted as SELF_ONLY still show up in /video/list/
         for the account owner.
    """
    s = (stored_id or "").strip()
    if not s:
        return None
    if not _is_publish_id(s):
        return s  # already a real id

    async with httpx.AsyncClient(timeout=30) as client:
        vid = await _fetch_publicly_available_post_id(client, access_token, s)
        if vid:
            return vid

        videos = await _list_videos(client, access_token, max_count=20)
        if not videos:
            return None
        if posted_at_epoch is not None:
            videos_sorted = sorted(
                videos,
                key=lambda v: abs(int(v.get("create_time") or 0) - int(posted_at_epoch)),
            )
            best = videos_sorted[0]
            # Guard: only trust the match if create_time is within 10 minutes.
            if abs(int(best.get("create_time") or 0) - int(posted_at_epoch)) <= 600:
                return str(best.get("id")) if best.get("id") else None
            return None
        # No timestamp → take most recent.
        videos.sort(key=lambda v: int(v.get("create_time") or 0), reverse=True)
        return str(videos[0].get("id")) if videos[0].get("id") else None


async def get_view_count(access_token: str, platform_post_id: str) -> int:
    """Look up view_count for a bare video_id.

    Caller is responsible for resolving publish_ids → video_ids via
    ``resolve_video_id`` first; this function does NOT do that fallback
    because it can't persist the resolved id back to the DB on its own.
    """
    if _is_publish_id(platform_post_id):
        # Nothing we can do here — the caller should have resolved upstream.
        return 0
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/video/query/?fields=view_count",
            json={"filters": {"video_ids": [platform_post_id]}},
            headers=headers,
        )
        if r.status_code == 401 and "scope_not_authorized" in r.text:
            raise TikTokStatsUnavailable(
                "TikTok per-video stats require the Display API `video.list` "
                "scope. Apply for it on the TikTok developer portal."
            )
        if r.status_code >= 400:
            raise PostingError(f"TikTok stats failed {r.status_code}: {r.text[:200]}")
        videos = ((r.json().get("data") or {}).get("videos")) or []
        if not videos:
            # TikTok returns 200 with empty videos[] when the video id is
            # gone (deleted by user / removed by moderation / private). Raise
            # PostDeletedError so the poller marks deleted_at and the
            # dashboard count drops. Transient glitches (rate-limit, edge
            # cache) are uncommon for the /video/query/ path; if they do
            # happen, the recovery path in the poller un-marks deleted_at
            # the next time the video shows up with a real view_count.
            raise PostDeletedError(
                f"TikTok video id {platform_post_id!r} not in query response "
                f"(deleted, private, or moderated)"
            )
        return int(videos[0].get("view_count") or 0)
