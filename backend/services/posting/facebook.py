"""Facebook Graph API — Page video publish adapter.

Requires `page_id` in kwargs (the Facebook Page id to post to).
"""
from __future__ import annotations

import httpx

from . import PostingError


GRAPH = "https://graph.facebook.com/v19.0"


async def upload_video(access_token: str, video_source: str, caption: str, **kwargs) -> dict:
    page_id = kwargs.get("page_id")
    if not page_id:
        raise PostingError("Facebook requires page_id")

    if video_source.startswith("http"):
        params = {"file_url": video_source, "description": caption or "", "access_token": access_token}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{GRAPH}/{page_id}/videos", params=params)
            if r.status_code >= 400:
                raise PostingError(f"FB upload failed {r.status_code}: {r.text[:200]}")
            vid = r.json().get("id")
            if not vid:
                raise PostingError("FB upload missing id")
            return {"platform_post_id": str(vid), "permalink": None}

    # Local file fallback — non-resumable single-shot upload
    with open(video_source, "rb") as f:
        files = {"source": (video_source, f, "video/mp4")}
        data = {"description": caption or "", "access_token": access_token}
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(f"{GRAPH}/{page_id}/videos", data=data, files=files)
            if r.status_code >= 400:
                raise PostingError(f"FB upload failed {r.status_code}: {r.text[:200]}")
            vid = r.json().get("id")
            if not vid:
                raise PostingError("FB upload missing id")
            return {"platform_post_id": str(vid), "permalink": None}


async def get_view_count(access_token: str, platform_post_id: str) -> int:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{GRAPH}/{platform_post_id}",
            params={"fields": "views", "access_token": access_token},
        )
        if r.status_code >= 400:
            return 0
        return int(r.json().get("views") or 0)
