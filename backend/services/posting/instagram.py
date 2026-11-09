"""Instagram Graph API v19 — Reels and carousel publish adapter.

Requires `ig_user_id` (the IG Business Account id) to be passed in or stored
alongside the token. The adapter reads it from `kwargs['ig_user_id']` first,
then from the variation row's `instagram_user_id` if available.
"""
from __future__ import annotations

import asyncio
import logging
import httpx

from . import PostingError, PostDeletedError

_log = logging.getLogger(__name__)


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
        #
        # Timeout raised from 36×5s (3 min) → 10s initial settle + 60×5s
        # (5 min). Large Reels (30–65 MB) regularly need 4–6 min for IG
        # to download, transcode, and mark FINISHED. The old cap caused
        # systematic timeouts across all accounts on every batch.
        await asyncio.sleep(10)  # initial settle — IG needs a moment to start
        for _ in range(60):
            await asyncio.sleep(5)
            s = await client.get(
                f"{GRAPH}/{creation_id}",
                params={
                    # NOTE: do NOT include "error" in fields — Meta returns
                    # a 400 OAuthException ("Tried accessing nonexisting field
                    # (error)") whenever the container is not in ERROR state,
                    # which makes every poll appear to fail and causes our
                    # loop to exhaust all retries even when the container is
                    # FINISHED and ready to publish.
                    "fields": "status_code,status",
                    "access_token": access_token,
                },
            )
            body = s.json() if s.status_code < 400 else {}
            status = body.get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                # Use the human-readable status string Meta provides.
                reason = body.get("status") or s.text[:200]
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


#: Instagram's own limits for a carousel.
CAROUSEL_MIN, CAROUSEL_MAX = 2, 10


def carousel_urls(slides_dir: str | None, public_base: str) -> list[str]:
    """Public URLs for a Brand output's slides as Instagram 4:5 JPEGs.

    Made from the 9:16 slides on request (/api/files-ig/), so an edit to a
    slide reaches Instagram without a rebuild.
    """
    from pathlib import Path
    from urllib.parse import quote

    if not slides_dir or not Path(slides_dir).is_dir():
        return []
    out = []
    for f in sorted(Path(slides_dir).iterdir()):
        if f.suffix.lower() == ".png" and f.stem.endswith("_9x16"):
            rel = str(f).lstrip("./")
            enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
            out.append(f"{public_base}/api/files-ig/{enc}")
    return out


async def upload_carousel(
    access_token: str, image_urls: list[str], caption: str,
    proxy_url: str | None = None, **kwargs,
) -> dict:
    """Publish a swipeable photo post (carousel).

    Instagram's API puts no sound on a carousel — music on a photo post is
    added in the app only — and has no draft, so this goes out live.
    """
    ig_user_id = kwargs.get("ig_user_id")
    if not ig_user_id:
        raise PostingError("Instagram requires ig_user_id (IG Business Account id)")
    if not CAROUSEL_MIN <= len(image_urls) <= CAROUSEL_MAX:
        raise PostingError(
            f"An Instagram carousel takes {CAROUSEL_MIN} to {CAROUSEL_MAX} slides; "
            f"this post has {len(image_urls)} — send Instagram the video instead"
        )

    async with httpx.AsyncClient(timeout=120, proxy=proxy_url) as client:
        children = []
        for url in image_urls:
            r = await client.post(
                f"{GRAPH}/{ig_user_id}/media",
                params={"image_url": url, "is_carousel_item": "true", "access_token": access_token},
            )
            if r.status_code >= 400:
                raise PostingError(f"IG carousel slide failed {r.status_code}: {r.text[:200]}")
            child = r.json().get("id")
            if not child:
                raise PostingError("IG carousel slide missing id")
            children.append(child)

        r = await client.post(
            f"{GRAPH}/{ig_user_id}/media",
            params={
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption or "",
                "access_token": access_token,
            },
        )
        if r.status_code >= 400:
            raise PostingError(f"IG carousel container failed {r.status_code}: {r.text[:200]}")
        creation_id = r.json().get("id")
        if not creation_id:
            raise PostingError("IG carousel container missing id")

        # Images are quick, but the container still has to say FINISHED.
        for _ in range(30):
            s = await client.get(
                f"{GRAPH}/{creation_id}",
                params={"fields": "status_code,status", "access_token": access_token},
            )
            body = s.json() if s.status_code < 400 else {}
            status = body.get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise PostingError(f"IG carousel error: {body.get('status') or s.text[:200]}")
            await asyncio.sleep(3)
        else:
            raise PostingError("IG carousel processing timed out")

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
        last_status, last_body = None, None
        for metric in ("views", "plays"):
            r = await client.get(
                f"{GRAPH}/{platform_post_id}/insights",
                params={"metric": metric, "access_token": access_token},
            )
            if r.status_code >= 400:
                last_status, last_body = r.status_code, r.text[:200]
                continue
            for row in r.json().get("data") or []:
                if row.get("name") == metric:
                    values = row.get("values") or []
                    if values:
                        return int(values[0].get("value") or 0)

        if last_status is not None:
            _log.warning(
                "IG insights unavailable for %s — both metrics failed "
                "(last HTTP %s: %s). Token may be missing "
                "instagram_manage_insights scope.",
                platform_post_id, last_status, last_body,
            )
        return 0


async def list_videos(
    access_token: str,
    ig_user_id: str | None = None,
    proxy_url: str | None = None,
) -> list[dict]:
    """Return the authed user's recent Instagram video/reel posts.

    Used by external-post discovery to find videos posted from a phone.
    Returns an empty list (never raises) when the scope is missing or the
    call fails — callers treat an empty result as "nothing to discover."

    Each item: {"id": str, "create_time": str (ISO-8601)}
    """
    uid = ig_user_id or "me"
    url = f"{GRAPH}/{uid}/media"
    params = {
        "fields": "id,timestamp,media_type",
        "limit": "20",
        "access_token": access_token,
    }
    try:
        async with httpx.AsyncClient(timeout=8, proxy=proxy_url) as client:
            r = await client.get(url, params=params)
        if r.status_code >= 400:
            return []
        return [
            {"id": m["id"], "create_time": m["timestamp"]}
            for m in (r.json().get("data") or [])
            if m.get("media_type") in ("VIDEO", "REEL")
        ]
    except Exception:
        return []
