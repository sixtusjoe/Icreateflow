"""OAuth scaffolding for TikTok / YouTube / Meta (IG+FB).

Provides:
- Authorize URL construction per platform
- Token exchange (code → access_token + refresh_token + expiry)
- State JWT signing/verification binding user+account+platform

Real-world posting uses the stored tokens elsewhere; this module only handles
the connection handshake.
"""
from __future__ import annotations

import os
import time
import json
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

from services.auth import SECRET_KEY, ALGORITHM


AUTHORIZE_URLS = {
    "tiktok": "https://www.tiktok.com/v2/auth/authorize/",
    "youtube": "https://accounts.google.com/o/oauth2/v2/auth",
    # Meta app covers both Instagram Business + Facebook Pages in one flow
    "meta": "https://www.facebook.com/v19.0/dialog/oauth",
}

TOKEN_URLS = {
    "tiktok": "https://open.tiktokapis.com/v2/oauth/token/",
    "youtube": "https://oauth2.googleapis.com/token",
    "meta": "https://graph.facebook.com/v19.0/oauth/access_token",
}

SCOPES = {
    # Only scopes the TikTok app is actually approved for. `username` (the
    # @handle) requires `user.info.profile` which isn't enabled on our app,
    # so we fall back to display_name in fetch_profile_handles and let the
    # user override via the Edit button if they want the real @handle.
    # `video.list` is required by /v2/video/query for view-count polling.
    "tiktok": "user.info.basic,video.publish,video.upload,video.list",
    "youtube": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
    "meta": (
        "instagram_basic,instagram_content_publish,"
        "pages_show_list,pages_manage_posts,pages_read_engagement,business_management"
    ),
}


def build_redirect_uri(redirect_base: str, platform: str) -> str:
    base = (redirect_base or "").rstrip("/")
    return f"{base}/api/oauth/{platform}/callback"


def sign_state(user_id: int, account_id: int, platform: str, kind: str = "account") -> str:
    """Short-lived JWT binding the connecting user to the account/variation + platform.

    `kind` is either 'account' (brand accounts, default) or 'variation' (artist_accounts).
    `account_id` carries the target row id regardless of kind.
    """
    payload = {
        "purpose": "oauth_state",
        "platform": platform,
        "user_id": user_id,
        "account_id": account_id,
        "kind": kind,
        "nonce": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_state(state: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("purpose") != "oauth_state":
        return None
    try:
        return {
            "platform": str(payload["platform"]),
            "user_id": int(payload["user_id"]),
            "account_id": int(payload["account_id"]),
            "kind": str(payload.get("kind") or "account"),
        }
    except (KeyError, ValueError):
        return None


def build_authorize_url(
    platform: str, client_id: str, redirect_uri: str, state: str
) -> str:
    """Return a platform-specific authorize URL."""
    if platform not in AUTHORIZE_URLS:
        raise ValueError(f"Unknown platform: {platform}")

    if platform == "tiktok":
        params = {
            "client_key": client_id,
            "response_type": "code",
            "scope": SCOPES["tiktok"],
            "redirect_uri": redirect_uri,
            "state": state,
        }
    elif platform == "youtube":
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPES["youtube"],
            "redirect_uri": redirect_uri,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    else:  # meta
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPES["meta"],
            "redirect_uri": redirect_uri,
            "state": state,
        }

    return f"{AUTHORIZE_URLS[platform]}?{urlencode(params)}"


async def exchange_code(
    platform: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange an auth code for access + refresh tokens."""
    if platform not in TOKEN_URLS:
        raise ValueError(f"Unknown platform: {platform}")

    async with httpx.AsyncClient(timeout=20) as client:
        if platform == "tiktok":
            resp = await client.post(
                TOKEN_URLS["tiktok"],
                data={
                    "client_key": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()
            return {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "scope": data.get("scope"),
                "platform_user_id": data.get("open_id"),
                "raw": data,
            }

        if platform == "youtube":
            resp = await client.post(
                TOKEN_URLS["youtube"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            data = resp.json()
            return {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "scope": data.get("scope"),
                "platform_user_id": None,
                "raw": data,
            }

        # meta
        resp = await client.get(
            TOKEN_URLS["meta"],
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        data = resp.json()
        return {
            "access_token": data.get("access_token"),
            "refresh_token": None,
            "expires_in": data.get("expires_in"),
            "scope": None,
            "platform_user_id": None,
            "raw": data,
        }


class ProfileFetchError(Exception):
    """Raised by fetch_profile_handles so callers can surface platform errors.

    fetch_profile_handles itself still swallows this and returns {} to avoid
    breaking OAuth callbacks; explicit callers (e.g. the refresh-profile
    endpoint) can re-raise via fetch_profile_handles_strict to show the
    platform's actual error message to the user.
    """


async def _fetch_profile_handles_impl(platform: str, access_token: str) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        if platform == "tiktok":
            # `username` needs user.info.profile; `display_name` only needs
            # user.info.basic. Try the combined call first, fall back to
            # display_name-only if the app isn't granted profile scope.
            async def _tt(fields: str):
                return await client.get(
                    "https://open.tiktokapis.com/v2/user/info/",
                    params={"fields": fields},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            r = await _tt("display_name,username")
            if r.status_code == 401 and "scope_not_authorized" in r.text:
                r = await _tt("display_name")
            if r.status_code >= 400:
                raise ProfileFetchError(f"tiktok {r.status_code}: {r.text[:200]}")
            data = (r.json() or {}).get("data", {}).get("user", {}) or {}
            name = data.get("username") or data.get("display_name")
            return {"tiktok_handle": name} if name else {}

        if platform == "youtube":
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code >= 400:
                raise ProfileFetchError(f"youtube {r.status_code}: {r.text[:200]}")
            items = (r.json() or {}).get("items", []) or []
            if not items:
                return {}
            snip = items[0].get("snippet", {}) or {}
            name = snip.get("customUrl") or snip.get("title")
            return {"youtube_handle": name} if name else {}

        if platform == "meta":
            r = await client.get(
                "https://graph.facebook.com/v19.0/me/accounts",
                params={
                    "fields": "name,instagram_business_account{username}",
                    "access_token": access_token,
                },
            )
            if r.status_code >= 400:
                raise ProfileFetchError(f"meta {r.status_code}: {r.text[:200]}")
            pages = (r.json() or {}).get("data", []) or []
            if not pages:
                return {}
            page = pages[0]
            out: dict[str, str] = {}
            if page.get("name"):
                out["facebook_handle"] = page["name"]
            ig = (page.get("instagram_business_account") or {}).get("username")
            if ig:
                out["instagram_handle"] = ig
            return out
        return {}


async def fetch_profile_handles(platform: str, access_token: str) -> dict[str, str]:
    """Return {'{platform}_handle': name} discovered from the connected account.

    Best-effort: swallows all errors so an OAuth callback never fails because
    of profile-lookup issues. Use `fetch_profile_handles_strict` if you want
    the platform error surfaced (e.g. the refresh-profile endpoint).
    """
    try:
        return await _fetch_profile_handles_impl(platform, access_token)
    except Exception:
        return {}


async def fetch_profile_handles_strict(platform: str, access_token: str) -> dict[str, str]:
    """Raise ProfileFetchError on platform failure instead of swallowing."""
    return await _fetch_profile_handles_impl(platform, access_token)


async def refresh_access_token(
    platform: str, refresh_token: str, client_id: str, client_secret: str
) -> dict[str, Any]:
    """Exchange a refresh_token for a fresh access_token.

    TikTok and Google (youtube) issue expiring access tokens with refresh tokens.
    Meta's long-lived page tokens don't rotate, so this is a no-op there.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        if platform == "tiktok":
            resp = await client.post(
                TOKEN_URLS["tiktok"],
                data={
                    "client_key": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()
            return {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token") or refresh_token,
                "expires_in": data.get("expires_in"),
                "raw": data,
            }
        if platform == "youtube":
            resp = await client.post(
                TOKEN_URLS["youtube"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            data = resp.json()
            return {
                "access_token": data.get("access_token"),
                "refresh_token": refresh_token,
                "expires_in": data.get("expires_in"),
                "raw": data,
            }
        # meta: no rotation
        return {"access_token": None, "refresh_token": refresh_token, "expires_in": None, "raw": {}}
