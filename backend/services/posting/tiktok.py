"""TikTok Content Posting API v2 adapter."""
from __future__ import annotations

import asyncio
import httpx

from . import PostingError, PostDeletedError, TikTokCreatorBlocked


API_BASE = "https://open.tiktokapis.com/v2"


async def get_creator_info(
    access_token: str, proxy_url: str | None = None,
) -> dict:
    """Fetch creator state for the post-to-TikTok UI.

    Required by TikTok's UX rules: the post-to-TikTok page MUST query this
    when it renders, display the creator's nickname so the user knows which
    account they're posting to, and block submission when the creator can't
    post right now (rate-limit / cooldown / account in violation).

    Returns the `data` block from `/v2/post/publish/creator_info/query/`:
        creator_avatar_url, creator_username, creator_nickname,
        privacy_level_options, comment_disabled, duet_disabled,
        stitch_disabled, max_video_post_duration_sec.

    Raises:
        TikTokCreatorBlocked when TikTok signals the creator can't post
            (HTTP 4xx with a recognised "creator_*" or "spam_risk_*" code).
        PostingError on any other failure.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as client:
        r = await client.post(
            f"{API_BASE}/post/publish/creator_info/query/",
            json={},
            headers=headers,
        )
        body = r.text or ""
        if r.status_code >= 400:
            # TikTok surfaces creator-side blocks as 4xx with codes like
            # "creator_in_audit", "spam_risk_user_banned",
            # "user_blocked_from_post", "creator_in_post_cooldown". Treat
            # the whole 4xx-with-code family as a blocked-creator signal.
            blocked_markers = (
                "creator_in_audit", "creator_in_post_cooldown",
                "user_blocked_from_post", "spam_risk", "creator_blocked",
            )
            if any(m in body for m in blocked_markers):
                raise TikTokCreatorBlocked(
                    f"TikTok creator cannot post right now: {body[:300]}"
                )
            raise PostingError(
                f"TikTok creator_info failed {r.status_code}: {body[:300]}"
            )
        data = (r.json().get("data") or {})
        # Normalise: TikTok returns an empty options array when the creator
        # is locked out without a 4xx. Treat that as a block too.
        if not data.get("privacy_level_options"):
            raise TikTokCreatorBlocked(
                f"TikTok creator_info returned no privacy options "
                f"(creator may be locked from posting): {body[:300]}"
            )
        return data


async def upload_video(
    access_token: str, video_source: str, caption: str,
    proxy_url: str | None = None, **kwargs,
) -> dict:
    """Publish a video to TikTok via the PULL_FROM_URL flow.

    `video_source` must be a publicly-reachable URL (e.g. a Drive direct-download
    link). Local uploads are not supported by this adapter in v1.

    Recognised kwargs:
      post_mode: "DIRECT_POST" (default) publishes immediately. "INBOX" sends
        the video to the user's TikTok inbox as a draft — they compose the
        caption / privacy / disclosure inside the TikTok app. INBOX skips
        every `post_info` field (TikTok ignores them for drafts).
      privacy_level: per `creator_info/query` `privacy_level_options` for
        this account. Required for DIRECT_POST.
      disable_duet, disable_stitch, disable_comment: bool, default False.
      brand_content_toggle: bool. True = third-party promotion.
        Forbidden combo: True + privacy_level=SELF_ONLY (TikTok rejects).
      brand_organic_toggle: bool. True = creator's own brand.
      video_cover_timestamp_ms: int, optional. Cover frame offset.
    """
    if not video_source.startswith("http"):
        raise PostingError("TikTok adapter only supports URL video sources in v1")

    post_mode = (kwargs.get("post_mode") or "DIRECT_POST").upper()
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if post_mode == "INBOX":
        # Inbox uploads are TikTok's "save as draft" path. The user composes
        # caption / privacy / disclosure inside their TikTok app once it
        # arrives. We send only the source — every `post_info` field is
        # ignored by this endpoint.
        init_body = {
            "source_info": {"source": "PULL_FROM_URL", "video_url": video_source},
        }
        async with httpx.AsyncClient(timeout=60, proxy=proxy_url) as client:
            r = await client.post(
                f"{API_BASE}/post/publish/inbox/video/init/",
                json=init_body,
                headers=headers,
            )
            if r.status_code >= 400:
                raise PostingError(
                    f"TikTok inbox init failed {r.status_code}: {r.text[:200]}"
                )
            data = r.json().get("data") or {}
            publish_id = data.get("publish_id")
            if not publish_id:
                raise PostingError(
                    f"TikTok inbox init missing publish_id: {r.text[:200]}"
                )
            # Drafts have no public post id until the user publishes from
            # their app. Skip status polling — the row is "done" from our
            # side once TikTok accepted the upload init.
            return {
                "platform_post_id": publish_id,
                "permalink": None,
                "draft": True,
            }

    privacy_level = kwargs.get("privacy_level") or "SELF_ONLY"
    brand_content_toggle = bool(kwargs.get("brand_content_toggle"))
    if brand_content_toggle and privacy_level == "SELF_ONLY":
        # TikTok rejects this combo. Fail fast with a clear error rather
        # than waste a round-trip and surface TikTok's 4xx text.
        raise PostingError(
            "TikTok rejects branded content with SELF_ONLY privacy — "
            "set privacy to PUBLIC_TO_EVERYONE (or any non-private level) "
            "before posting branded content."
        )
    post_info = {
        "title": (caption or "")[:2200],
        "privacy_level": privacy_level,
        "disable_duet": bool(kwargs.get("disable_duet", False)),
        "disable_stitch": bool(kwargs.get("disable_stitch", False)),
        "disable_comment": bool(kwargs.get("disable_comment", False)),
        "brand_content_toggle": brand_content_toggle,
        "brand_organic_toggle": bool(kwargs.get("brand_organic_toggle", False)),
    }
    if kwargs.get("video_cover_timestamp_ms") is not None:
        post_info["video_cover_timestamp_ms"] = int(kwargs["video_cover_timestamp_ms"])
    init_body = {
        "post_info": post_info,
        "source_info": {"source": "PULL_FROM_URL", "video_url": video_source},
    }

    async with httpx.AsyncClient(timeout=60, proxy=proxy_url) as client:
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
    proxy_url: str | None = None,
    **kwargs,
) -> dict:
    """Publish a swipeable photo slideshow via TikTok's content/init endpoint.

    `photo_urls` must all be publicly-reachable HTTPS URLs. TikTok will pull
    each image and stitch them into a slideshow post. Stats are queried via
    the same /v2/video/query/ endpoint as videos (slideshows share the ID space).

    Recognised kwargs (mirrors `upload_video`):
      post_mode: "DIRECT_POST" (default) publishes immediately. "MEDIA_UPLOAD"
        sends to the user's TikTok inbox as a draft — they edit privacy and
        compose inside the TikTok app. MEDIA_UPLOAD strips every `post_info`
        field except the source.
      disable_comment: bool. Photos cannot be Duet'd or Stitched, so those
        flags don't apply.
      brand_content_toggle, brand_organic_toggle: same semantics as video.
        Branded + SELF_ONLY is rejected pre-call.
    """
    if not photo_urls:
        raise PostingError("TikTok slideshow needs at least one photo URL")
    for u in photo_urls:
        if not u.startswith("http"):
            raise PostingError("TikTok slideshow requires public URLs, not local paths")

    post_mode = (kwargs.get("post_mode") or "DIRECT_POST").upper()
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if post_mode == "MEDIA_UPLOAD":
        # Inbox / draft path. The slideshow lands in the creator's TikTok
        # inbox; they pick caption / privacy / disclosure inside the app.
        init_body = {
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": 0,
                "photo_images": photo_urls,
            },
            "post_mode": "MEDIA_UPLOAD",
            "media_type": "PHOTO",
        }
        async with httpx.AsyncClient(timeout=60, proxy=proxy_url) as client:
            r = await client.post(
                f"{API_BASE}/post/publish/content/init/", json=init_body, headers=headers
            )
            if r.status_code >= 400:
                raise PostingError(
                    f"TikTok slideshow inbox init failed {r.status_code}: {r.text[:300]}"
                )
            data = r.json().get("data") or {}
            publish_id = data.get("publish_id")
            if not publish_id:
                raise PostingError(
                    f"TikTok slideshow inbox init missing publish_id: {r.text[:200]}"
                )
            return {
                "platform_post_id": publish_id,
                "permalink": None,
                "draft": True,
            }

    brand_content_toggle = bool(kwargs.get("brand_content_toggle"))
    if brand_content_toggle and privacy_level == "SELF_ONLY":
        raise PostingError(
            "TikTok rejects branded content with SELF_ONLY privacy — "
            "set privacy to PUBLIC_TO_EVERYONE (or any non-private level) "
            "before posting branded content."
        )

    # TikTok renders both `title` and `description` on slideshows — putting the
    # caption in both duplicates it. Leave title empty; use description only.
    init_body = {
        "post_info": {
            "title": "",
            "description": (caption or "")[:4000],
            "privacy_level": privacy_level,
            "disable_comment": bool(kwargs.get("disable_comment", False)),
            "auto_add_music": auto_add_music,
            "brand_content_toggle": brand_content_toggle,
            "brand_organic_toggle": bool(kwargs.get("brand_organic_toggle", False)),
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": photo_urls,
        },
        "post_mode": "DIRECT_POST",
        "media_type": "PHOTO",
    }

    async with httpx.AsyncClient(timeout=60, proxy=proxy_url) as client:
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
    proxy_url: str | None = None,
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

    async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as client:
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


async def get_view_count(
    access_token: str, platform_post_id: str, proxy_url: str | None = None,
) -> int:
    """Look up view_count for a bare video_id.

    Caller is responsible for resolving publish_ids → video_ids via
    ``resolve_video_id`` first; this function does NOT do that fallback
    because it can't persist the resolved id back to the DB on its own.
    """
    if _is_publish_id(platform_post_id):
        # Nothing we can do here — the caller should have resolved upstream.
        return 0
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as client:
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
            # TikTok returns 200 + empty videos[] when the video is gone
            # (deleted by user, removed by moderation, or set private).
            # Raise PostDeletedError so the poller marks deleted_at on this
            # row and it drops from the live post count. The view_count column
            # is NOT cleared by the poller on deletion, so accumulated views
            # still appear on the dashboard (the dashboard sums views from all
            # posted rows, deleted or not).
            raise PostDeletedError(
                f"TikTok video id {platform_post_id!r} not in query response "
                f"(deleted, private, or moderated)"
            )
        return int(videos[0].get("view_count") or 0)
