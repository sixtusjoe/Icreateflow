"""TikTok Content Posting API v2 adapter."""
from __future__ import annotations

import asyncio
import httpx

from . import PostingError


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

    init_body = {
        "post_info": {
            "title": (caption or "")[:90],  # photo title limit is stricter
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


async def get_view_count(access_token: str, platform_post_id: str) -> int:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/video/query/?fields=view_count",
            json={"filters": {"video_ids": [platform_post_id]}},
            headers=headers,
        )
        if r.status_code >= 400:
            raise PostingError(f"TikTok stats failed {r.status_code}: {r.text[:200]}")
        videos = ((r.json().get("data") or {}).get("videos")) or []
        if not videos:
            return 0
        return int(videos[0].get("view_count") or 0)
