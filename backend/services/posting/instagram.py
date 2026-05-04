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


async def upload_video(
    access_token: str, video_source: str, caption: str,
    proxy_url: str | None = None, **kwargs,
) -> dict:
    ig_user_id = kwargs.get("ig_user_id")
    if not ig_user_id:
        raise PostingError("Instagram requires ig_user_id (IG Business Account id)")
    if not video_source.startswith("http"):
        raise PostingError("Instagram requires a public video_url — upload the clip to Drive first")

    async with httpx.AsyncClient(timeout=120, proxy=proxy_url) as client:
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

        # Poll container status. Request `status` and `error` alongside
        # `status_code` so when the container goes ERROR we surface the
        # actual reason (codec, length, aspect ratio, fetch failure)
        # instead of just `{"status_code":"ERROR","id":"…"}` — that was
        # opaque enough to send us chasing the wrong root cause on a
        # past lancastarmoonnews failure.
        for _ in range(36):
            await asyncio.sleep(5)
            s = await client.get(
                f"{GRAPH}/{creation_id}",
                params={
                    "fields": "status_code,status,error",
                    "access_token": access_token,
                },
            )
            body = s.json() if s.status_code < 400 else {}
            status = body.get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                # `error` is the structured Meta error object when present;
                # `status` is the human-readable processing status string.
                err_obj = body.get("error") or {}
                reason = (
                    err_obj.get("error_user_msg")
                    or err_obj.get("message")
                    or body.get("status")
                    or s.text[:200]
                )
                raise PostingError(f"IG container error: {reason}")
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


async def get_view_count(
    access_token: str, platform_post_id: str, proxy_url: str | None = None,
) -> int:
    async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as client:
        # Step 1: existence probe. GET /{media-id}?fields=id is the cheapest
        # call we can make and it doesn't need insights permission. If the
        # media is gone Meta returns 4xx with 'does not exist' or
        # 'Unsupported get request' — we promote that to PostDeletedError.
        # Doing this BEFORE the insights call lets us catch deletions even
        # for accounts where insights are silently 0 (no view data populated
        # yet, missing scope, etc.).
        probe = await client.get(
            f"{GRAPH}/{platform_post_id}",
            params={"fields": "id", "access_token": access_token},
        )
        if probe.status_code >= 400:
            text = (probe.text or "")[:300]
            low = text.lower()
            if (
                "does not exist" in low
                or "unsupported get request" in low
                or '"code":100' in text
            ):
                raise PostDeletedError(
                    f"IG media id {platform_post_id!r} not found: {text[:200]}"
                )
            # Other 4xx (rate limit, transient) — fall through; we'll return
            # 0 below and the monotonic poller will keep the previous count.

        # Step 2: insights for view count. Meta deprecated `plays` in Graph
        # API v22.0+; supported view-equivalent for Reels is `views`. Fall
        # back to `plays` for older API versions.
        for metric in ("views", "plays"):
            r = await client.get(
                f"{GRAPH}/{platform_post_id}/insights",
                params={"metric": metric, "access_token": access_token},
            )
            if r.status_code >= 400:
                continue
            for row in r.json().get("data") or []:
                if row.get("name") == metric:
                    values = row.get("values") or []
                    if values:
                        return int(values[0].get("value") or 0)
        return 0
