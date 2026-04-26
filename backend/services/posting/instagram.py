"""Instagram Graph API v19 — Reels publish adapter.

Requires `ig_user_id` (the IG Business Account id) to be passed in or stored
alongside the token. The adapter reads it from `kwargs['ig_user_id']` first,
then from the variation row's `instagram_user_id` if available.
"""
from __future__ import annotations

import asyncio
import httpx

from . import PostingError, PostDeletedError


GRAPH = "https://graph.facebook.com/v19.0"


async def upload_video(access_token: str, video_source: str, caption: str, **kwargs) -> dict:
    ig_user_id = kwargs.get("ig_user_id")
    if not ig_user_id:
        raise PostingError("Instagram requires ig_user_id (IG Business Account id)")
    if not video_source.startswith("http"):
        raise PostingError("Instagram requires a public video_url — upload the clip to Drive first")

    async with httpx.AsyncClient(timeout=120) as client:
        # Create container
        r = await client.post(
            f"{GRAPH}/{ig_user_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_source,
                "caption": caption or "",
                "access_token": access_token,
            },
        )
        if r.status_code >= 400:
            raise PostingError(f"IG container failed {r.status_code}: {r.text[:200]}")
        creation_id = r.json().get("id")
        if not creation_id:
            raise PostingError("IG container missing id")

        # Poll container status
        for _ in range(36):
            await asyncio.sleep(5)
            s = await client.get(
                f"{GRAPH}/{creation_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            status = s.json().get("status_code") if s.status_code < 400 else None
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise PostingError(f"IG container error: {s.text[:200]}")
        else:
            raise PostingError("IG container processing timed out")

        p = await client.post(
            f"{GRAPH}/{ig_user_id}/media_publish",
            params={"creation_id": creation_id, "access_token": access_token},
        )
        if p.status_code >= 400:
            raise PostingError(f"IG publish failed {p.status_code}: {p.text[:200]}")
        media_id = p.json().get("id")
        if not media_id:
            raise PostingError("IG publish missing id")
        return {"platform_post_id": media_id, "permalink": None}


async def get_view_count(access_token: str, platform_post_id: str) -> int:
    # Meta deprecated `plays` in Graph API v22.0+. The supported view-equivalent
    # metric for Reels is now `views`. Fall back to `plays` for the v19-and-below
    # window in case the app gets pinned to an older version.
    last_err_text = ""
    async with httpx.AsyncClient(timeout=30) as client:
        for metric in ("views", "plays"):
            r = await client.get(
                f"{GRAPH}/{platform_post_id}/insights",
                params={"metric": metric, "access_token": access_token},
            )
            if r.status_code >= 400:
                last_err_text = (r.text or "")[:300]
                continue
            for row in r.json().get("data") or []:
                if row.get("name") == metric:
                    values = row.get("values") or []
                    if values:
                        return int(values[0].get("value") or 0)
        # Both metric attempts errored — sniff for the deleted-post signal
        # Meta returns when the media id is gone. They use a few wordings:
        #   - "Object with ID '...' does not exist"
        #   - "Unsupported get request. Object with ID ..."
        #   - error.code 100 + error_subcode 33 ("does not exist, cannot be
        #     loaded due to missing permissions, or does not support this
        #     operation")
        # Match on substrings so we don't depend on exact JSON path.
        low = last_err_text.lower()
        if last_err_text and (
            "does not exist" in low
            or "unsupported get request" in low
            or '"code":100' in last_err_text
        ):
            raise PostDeletedError(
                f"IG media id {platform_post_id!r} not found: {last_err_text[:200]}"
            )
        return 0
