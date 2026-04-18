"""YouTube Data API v3 adapter — resumable upload for Shorts."""
from __future__ import annotations

import json
import httpx

from . import PostingError


UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3/videos"


async def _fetch_bytes(source: str) -> bytes:
    if source.startswith("http"):
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            r = await client.get(source)
            if r.status_code >= 400:
                raise PostingError(f"Could not fetch source URL ({r.status_code})")
            return r.content
    # local path
    with open(source, "rb") as f:
        return f.read()


async def upload_video(access_token: str, video_source: str, caption: str, **kwargs) -> dict:
    body = await _fetch_bytes(video_source)
    metadata = {
        "snippet": {"title": (caption or "Clip")[:100], "description": caption or ""},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/*",
        "X-Upload-Content-Length": str(len(body)),
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
            headers=headers,
            content=json.dumps(metadata),
        )
        if r.status_code >= 400 or "Location" not in r.headers:
            raise PostingError(f"YouTube resumable init failed {r.status_code}: {r.text[:200]}")
        upload_url = r.headers["Location"]

        r2 = await client.put(
            upload_url, content=body, headers={"Content-Type": "video/*"}
        )
        if r2.status_code >= 400:
            raise PostingError(f"YouTube upload failed {r2.status_code}: {r2.text[:200]}")
        video_id = r2.json().get("id")
        if not video_id:
            raise PostingError(f"YouTube upload missing id: {r2.text[:200]}")
        return {
            "platform_post_id": video_id,
            "permalink": f"https://www.youtube.com/watch?v={video_id}",
        }


async def get_view_count(access_token: str, platform_post_id: str) -> int:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            API_URL,
            params={"part": "statistics", "id": platform_post_id},
            headers=headers,
        )
        if r.status_code >= 400:
            raise PostingError(f"YouTube stats failed {r.status_code}: {r.text[:200]}")
        items = r.json().get("items") or []
        if not items:
            return 0
        return int((items[0].get("statistics") or {}).get("viewCount") or 0)
