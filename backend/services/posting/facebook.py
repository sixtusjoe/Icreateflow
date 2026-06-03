"""Facebook Graph API — Page video publish adapter.

Requires `page_id` in kwargs (the Facebook Page id to post to).
"""
from __future__ import annotations

import httpx

from . import PostingError, PostDeletedError


GRAPH = "https://graph.facebook.com/v19.0"


async def upload_video(
    access_token: str, video_source: str, caption: str,
    proxy_url: str | None = None, **kwargs,
) -> dict:
    page_id = kwargs.get("page_id")
    if not page_id:
        raise PostingError("Facebook requires page_id")

    if video_source.startswith("http"):
        params = {"file_url": video_source, "description": caption or "", "access_token": access_token}
        async with httpx.AsyncClient(timeout=300, proxy=proxy_url) as client:
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
        async with httpx.AsyncClient(timeout=600, proxy=proxy_url) as client:
            r = await client.post(f"{GRAPH}/{page_id}/videos", data=data, files=files)
            if r.status_code >= 400:
                raise PostingError(f"FB upload failed {r.status_code}: {r.text[:200]}")
            vid = r.json().get("id")
            if not vid:
                raise PostingError("FB upload missing id")
            return {"platform_post_id": str(vid), "permalink": None}


async def get_view_count(
    access_token: str, platform_post_id: str, proxy_url: str | None = None,
) -> int:
    async with httpx.AsyncClient(timeout=8, proxy=proxy_url) as client:
        # Existence probe + node `views` field (used as fallback value).
        # If the post is gone Meta 4xx's with 'does not exist' / 'unsupported
        # get request' / code:100 — promote to PostDeletedError.
        r = await client.get(
            f"{GRAPH}/{platform_post_id}",
            params={"fields": "id,views", "access_token": access_token},
        )
        if r.status_code >= 400:
            text = (r.text or "")[:300]
            low = text.lower()
            if (
                "does not exist" in low
                or "unsupported get request" in low
                or '"code":100' in text
            ):
                raise PostDeletedError(
                    f"FB post id {platform_post_id!r} not found: {text[:200]}"
                )
            return 0
        node_views = int(r.json().get("views") or 0)

        # Primary metric: total_video_views from video_insights matches what
        # Meta Creator Studio shows. The node `views` field is a different
        # (lower) aggregation. Fall back to node_views on any 4xx so older
        # page tokens / reel-type posts that don't support insights still work.
        ins = await client.get(
            f"{GRAPH}/{platform_post_id}/video_insights",
            params={"metric": "total_video_views", "access_token": access_token},
        )
        if ins.status_code >= 400:
            return node_views
        for row in ins.json().get("data") or []:
            if row.get("name") == "total_video_views":
                values = row.get("values") or []
                if values:
                    return int(values[0].get("value") or 0)
        return node_views


async def list_videos(
    access_token: str,
    page_id: str | None = None,
    proxy_url: str | None = None,
) -> list[dict]:
    """Return the authed page's recent uploaded videos.

    Used by external-post discovery to find videos posted from a phone or
    Creator Studio. Returns an empty list (never raises) on any error.

    Each item: {"id": str, "create_time": str (ISO-8601)}
    """
    if not page_id:
        return []
    url = f"{GRAPH}/{page_id}/videos"
    params = {
        "fields": "id,created_time",
        "type": "uploaded",
        "limit": "20",
        "access_token": access_token,
    }
    try:
        async with httpx.AsyncClient(timeout=8, proxy=proxy_url) as client:
            r = await client.get(url, params=params)
        if r.status_code >= 400:
            return []
        return [
            {"id": v["id"], "create_time": v["created_time"]}
            for v in (r.json().get("data") or [])
            if v.get("id")
        ]
    except Exception:
        return []
