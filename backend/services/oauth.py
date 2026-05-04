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

import logging
import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

log = logging.getLogger(__name__)

from services.auth import SECRET_KEY, ALGORITHM


AUTHORIZE_URLS = {
    "tiktok": "https://www.tiktok.com/v2/auth/authorize/",
    "youtube": "https://accounts.google.com/o/oauth2/v2/auth",
    # Meta app covers Facebook Pages (and legacy IG-via-FB-login when present)
    "meta": "https://www.facebook.com/v19.0/dialog/oauth",
    # Newer standalone "Instagram API with Instagram Login" flow — separate app
    # credentials, separate consent screen, separate scopes.
    "instagram": "https://www.instagram.com/oauth/authorize",
}

TOKEN_URLS = {
    "tiktok": "https://open.tiktokapis.com/v2/oauth/token/",
    "youtube": "https://oauth2.googleapis.com/token",
    "meta": "https://graph.facebook.com/v19.0/oauth/access_token",
    # IG Login: short-lived code→token at api.instagram.com, then exchange for
    # long-lived (60d) via graph.instagram.com/access_token.
    "instagram": "https://api.instagram.com/oauth/access_token",
}

_DEFAULT_TIKTOK_SCOPES = "user.info.basic,video.publish,video.upload"
_DEFAULT_YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/youtube.readonly"
)
_DEFAULT_INSTAGRAM_SCOPES = (
    # Instagram API with Instagram Login (standalone IG app, NOT Facebook Login).
    #   instagram_business_basic             — IG identity/profile
    #   instagram_business_content_publish   — publish reels/posts
    #   instagram_business_manage_insights   — read post insights (plays/views)
    "instagram_business_basic,instagram_business_content_publish,"
    "instagram_business_manage_insights"
)
_DEFAULT_META_SCOPES = (
    # Post + read-views on FB Pages and IG Business accounts.
    #   instagram_basic             — IG identity
    #   instagram_content_publish   — publish reels/posts
    #   instagram_manage_insights   — read IG post insights (plays/views)
    #   pages_show_list             — list pages
    #   pages_manage_posts          — publish to a page
    #   pages_read_engagement       — read page post 'views' field
    # All six are granted automatically to app admins/developers/testers
    # in dev mode; end-users require App Review. Override via env
    # META_SCOPES to add/remove (e.g. business_management for BM APIs).
    "instagram_basic,instagram_content_publish,instagram_manage_insights,"
    "pages_show_list,pages_manage_posts,pages_read_engagement"
)

SCOPES = {
    # TikTok: only scopes the app is approved for on the TikTok developer
    # portal can be requested here — unknown scopes make the consent screen
    # fail. Override via env (no code deploy) when you enable additional
    # scopes on the portal side (e.g. user.info.stats, or video.list once
    # the Display API product is approved).
    #   export TIKTOK_SCOPES="user.info.basic,video.publish,video.upload,user.info.stats"
    "tiktok":    os.environ.get("TIKTOK_SCOPES",    _DEFAULT_TIKTOK_SCOPES),
    "youtube":   os.environ.get("YOUTUBE_SCOPES",   _DEFAULT_YOUTUBE_SCOPES),
    "meta":      os.environ.get("META_SCOPES",      _DEFAULT_META_SCOPES),
    "instagram": os.environ.get("INSTAGRAM_SCOPES", _DEFAULT_INSTAGRAM_SCOPES),
}


def build_redirect_uri(redirect_base: str, platform: str) -> str:
    base = (redirect_base or "").rstrip("/")
    return f"{base}/api/oauth/{platform}/callback"


def sign_state(
    user_id: int, account_id: int, platform: str,
    kind: str = "account",
    flow: str = "popup",
    return_to: str | None = None,
) -> str:
    """Short-lived JWT binding the connecting user to the account/variation + platform.

    `kind` is either 'account' (brand accounts, default) or 'variation' (artist_accounts).
    `account_id` carries the target row id regardless of kind.

    `flow` is "popup" (default — render close-html that postMessages the
    opener) or "redirect" (return a 302 to `return_to` with a query
    string carrying the result). Standalone-IG OAuth on mobile has to
    use redirect because iOS deep-links instagram.com/oauth into the
    Instagram app, which can't postMessage back to a popup opener.

    `return_to` is the absolute URL to send the browser back to when
    flow=redirect; ignored for flow=popup.
    """
    payload = {
        "purpose": "oauth_state",
        "platform": platform,
        "user_id": user_id,
        "account_id": account_id,
        "kind": kind,
        "flow": flow,
        "return_to": return_to or "",
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
            "flow": str(payload.get("flow") or "popup"),
            "return_to": str(payload.get("return_to") or ""),
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
    elif platform == "meta":
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPES["meta"],
            "redirect_uri": redirect_uri,
            "state": state,
        }
    else:  # instagram (standalone IG Login)
        params = {
            "client_id": client_id,
            "response_type": "code",
            # IG Login expects space- or comma-separated scopes; use comma
            # to match our stored convention.
            "scope": SCOPES["instagram"],
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

        if platform == "instagram":
            # Step 1: short-lived token at api.instagram.com
            resp = await client.post(
                TOKEN_URLS["instagram"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            short = resp.json() or {}
            short_token = short.get("access_token")
            ig_user_id = short.get("user_id")
            long_token = None
            long_expires_in = None
            if short_token:
                # Step 2: exchange short-lived → long-lived (~60d) at graph.instagram.com
                try:
                    r2 = await client.get(
                        "https://graph.instagram.com/access_token",
                        params={
                            "grant_type": "ig_exchange_token",
                            "client_secret": client_secret,
                            "access_token": short_token,
                        },
                    )
                    long_data = r2.json() or {}
                    long_token = long_data.get("access_token")
                    long_expires_in = long_data.get("expires_in")
                except Exception:
                    long_data = {}
            return {
                "access_token": long_token or short_token,
                "refresh_token": None,  # IG uses long-lived + refresh via /refresh_access_token
                "expires_in": long_expires_in,
                "scope": SCOPES["instagram"],
                "platform_user_id": str(ig_user_id) if ig_user_id else None,
                "raw": {"short": short, "long": long_data if short_token else None},
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
        short_user_token = data.get("access_token")
        # Step 2: short-lived (~1h) → long-lived (~60d) user token. Long-lived
        # user tokens mint long-lived Page access tokens that survive
        # subsequent user re-authentications. Without this, every new variation
        # connect on the same FB user invalidates the prior variations' tokens.
        long_user_token = short_user_token
        long_expires_in = data.get("expires_in")
        if short_user_token:
            try:
                ll = await client.get(
                    TOKEN_URLS["meta"],
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "fb_exchange_token": short_user_token,
                    },
                )
                ll_data = ll.json() or {}
                if ll_data.get("access_token"):
                    long_user_token = ll_data["access_token"]
                    long_expires_in = ll_data.get("expires_in") or long_expires_in
            except Exception:
                pass
        return {
            "access_token": long_user_token,
            "refresh_token": None,
            "expires_in": long_expires_in,
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


async def _fetch_profile_handles_impl(
    platform: str,
    access_token: str,
    prefer_page_id: str | None = None,
    prefer_ig_id: str | None = None,
) -> dict[str, str]:
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

        if platform == "instagram":
            # Instagram API with Instagram Login profile lookup. Unlike
            # the Meta Graph API (which requires /vN.N/ in the path),
            # graph.instagram.com rejects the version prefix with
            # `IGApiException code 100 — Unsupported request - method
            # type: get` because it parses `v19.0` as a node id and
            # `me` as nothing valid. The version-less path is the one
            # documented for Instagram-Login tokens.
            #
            # Request both `user_id` and `username`. `username` is the
            # @handle we display in the OAuth tile; `user_id` is the IG
            # Business Account id used by /api/oauth/instagram/callback
            # downstream and by the FB/IG adapter for posting (matches
            # what the Meta-flow path returns).
            r = await client.get(
                "https://graph.instagram.com/me",
                params={
                    "fields": "user_id,username",
                    "access_token": access_token,
                },
            )
            if r.status_code >= 400:
                raise ProfileFetchError(f"instagram {r.status_code}: {r.text[:200]}")
            data = r.json() or {}
            name = data.get("username")
            out: dict = {}
            if name:
                out["instagram_handle"] = name
            if data.get("user_id"):
                out["instagram_user_id"] = str(data["user_id"])
            return out

        if platform == "meta":
            # Meta's new granular-permission consent flow breaks /me/accounts:
            # the token is scoped to specific Page/IG IDs, but /me/accounts
            # only returns entries for the legacy "all Pages" grant and comes
            # back empty under granular scopes. Instead, read target_ids out
            # of the token's granular_scopes via /debug_token and query the
            # assets by ID directly — which works under both models.
            dbg = await client.get(
                "https://graph.facebook.com/debug_token",
                params={"input_token": access_token, "access_token": access_token},
            )
            if dbg.status_code >= 400:
                raise ProfileFetchError(f"meta debug_token {dbg.status_code}: {dbg.text[:200]}")
            granular = ((dbg.json() or {}).get("data") or {}).get("granular_scopes") or []
            page_ids: list[str] = []
            ig_ids: list[str] = []
            for g in granular:
                scope = g.get("scope")
                tids = g.get("target_ids") or []
                if scope == "pages_show_list":
                    page_ids = [str(t) for t in tids]
                elif scope == "instagram_basic":
                    ig_ids = [str(t) for t in tids]
            out: dict[str, str] = {}
            # Pick the page that matches the variation's stored facebook_user_id
            # (if any). Falls back to first page when no preference or no match.
            chosen_page_id: str | None = None
            if page_ids:
                if prefer_page_id and prefer_page_id in page_ids:
                    chosen_page_id = prefer_page_id
                else:
                    chosen_page_id = page_ids[0]
            chosen_ig_id: str | None = None
            if ig_ids:
                if prefer_ig_id and prefer_ig_id in ig_ids:
                    chosen_ig_id = prefer_ig_id
                else:
                    chosen_ig_id = ig_ids[0]
            if chosen_page_id:
                pr = await client.get(
                    f"https://graph.facebook.com/v19.0/{chosen_page_id}",
                    params={
                        # Request the Page-scoped access_token too — posting
                        # to /{page_id}/videos needs a Page token, not the
                        # user token. Caller stores this in facebook_token.
                        "fields": "name,access_token,instagram_business_account{username,id}",
                        "access_token": access_token,
                    },
                )
                if pr.status_code < 400:
                    pd = pr.json() or {}
                    if pd.get("name"):
                        out["facebook_handle"] = pd["name"]
                    out["facebook_user_id"] = str(chosen_page_id)
                    if pd.get("access_token"):
                        out["facebook_page_access_token"] = pd["access_token"]
                    ig_edge = pd.get("instagram_business_account") or {}
                    if ig_edge.get("username"):
                        out["instagram_handle"] = ig_edge["username"]
                    if ig_edge.get("id"):
                        out["instagram_user_id"] = str(ig_edge["id"])
            # Fallback: IG was granted but no Page (standalone IG-via-Meta case).
            if not out.get("instagram_handle") and chosen_ig_id:
                ir = await client.get(
                    f"https://graph.facebook.com/v19.0/{chosen_ig_id}",
                    params={"fields": "username", "access_token": access_token},
                )
                if ir.status_code < 400:
                    idata = ir.json() or {}
                    if idata.get("username"):
                        out["instagram_handle"] = idata["username"]
                    out["instagram_user_id"] = str(chosen_ig_id)
            return out
        return {}


async def fetch_meta_assets(access_token: str) -> list[dict]:
    """Return EVERY asset granted to this Meta user token.

    Used by the multi-asset OAuth flow: one OAuth grant can authorize multiple
    Pages + IG accounts; the admin then picks which asset belongs to which
    variation. Each entry in the returned list has:
      - page_id, page_name, page_access_token (long-lived if user token is)
      - ig_user_id, ig_handle (when the Page has a linked IG Business account)

    Pages with no linked IG still appear (ig_user_id=None). Standalone IG
    accounts granted without a Page also appear (page_id=None).
    """
    out: list[dict] = []
    seen_ig: set[str] = set()
    async with httpx.AsyncClient(timeout=20) as client:
        dbg = await client.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": access_token, "access_token": access_token},
        )
        if dbg.status_code >= 400:
            raise ProfileFetchError(f"meta debug_token {dbg.status_code}: {dbg.text[:200]}")
        granular = ((dbg.json() or {}).get("data") or {}).get("granular_scopes") or []
        page_ids: list[str] = []
        ig_ids: list[str] = []
        for g in granular:
            scope = g.get("scope")
            tids = g.get("target_ids") or []
            if scope == "pages_show_list":
                page_ids = [str(t) for t in tids]
            elif scope == "instagram_basic":
                ig_ids = [str(t) for t in tids]
        for pid in page_ids:
            pr = await client.get(
                f"https://graph.facebook.com/v19.0/{pid}",
                params={
                    "fields": "name,access_token,instagram_business_account{username,id}",
                    "access_token": access_token,
                },
            )
            if pr.status_code >= 400:
                continue
            pd = pr.json() or {}
            ig_edge = pd.get("instagram_business_account") or {}
            ig_uid = str(ig_edge.get("id")) if ig_edge.get("id") else None
            entry = {
                "page_id": pid,
                "page_name": pd.get("name"),
                "page_access_token": pd.get("access_token"),
                "ig_user_id": ig_uid,
                "ig_handle": ig_edge.get("username"),
            }
            out.append(entry)
            if ig_uid:
                seen_ig.add(ig_uid)
        # Standalone IG accounts granted without a Page wrapper.
        for iid in ig_ids:
            if iid in seen_ig:
                continue
            ir = await client.get(
                f"https://graph.facebook.com/v19.0/{iid}",
                params={"fields": "username", "access_token": access_token},
            )
            if ir.status_code >= 400:
                continue
            idata = ir.json() or {}
            out.append({
                "page_id": None,
                "page_name": None,
                "page_access_token": None,
                "ig_user_id": iid,
                "ig_handle": idata.get("username"),
            })
    return out


async def fetch_profile_handles(
    platform: str,
    access_token: str,
    prefer_page_id: str | None = None,
    prefer_ig_id: str | None = None,
) -> dict[str, str]:
    """Return {'{platform}_handle': name} discovered from the connected account.

    Best-effort: swallows all errors so an OAuth callback never fails because
    of profile-lookup issues. Use `fetch_profile_handles_strict` if you want
    the platform error surfaced (e.g. the refresh-profile endpoint).

    For Meta: when the granular-permission consent grants multiple Pages or IG
    accounts, `prefer_page_id` / `prefer_ig_id` pick the matching one (e.g. the
    Page that this variation was previously connected to). Falls back to the
    first granted asset.
    """
    try:
        return await _fetch_profile_handles_impl(
            platform, access_token,
            prefer_page_id=prefer_page_id, prefer_ig_id=prefer_ig_id,
        )
    except Exception as e:
        # Don't block the OAuth callback, but surface why usernames
        # weren't auto-filled so admins can diagnose in server logs.
        log.warning("fetch_profile_handles(%s) failed: %s", platform, e)
        return {}


async def fetch_profile_handles_strict(
    platform: str,
    access_token: str,
    prefer_page_id: str | None = None,
    prefer_ig_id: str | None = None,
) -> dict[str, str]:
    """Raise ProfileFetchError on platform failure instead of swallowing."""
    return await _fetch_profile_handles_impl(
        platform, access_token,
        prefer_page_id=prefer_page_id, prefer_ig_id=prefer_ig_id,
    )


async def refresh_access_token(
    platform: str, refresh_token: str, client_id: str, client_secret: str,
    proxy_url: str | None = None,
) -> dict[str, Any]:
    """Exchange a refresh_token for a fresh access_token.

    TikTok and Google (youtube) issue expiring access tokens with refresh tokens.
    Meta's long-lived page tokens don't rotate, so this is a no-op there.
    """
    async with httpx.AsyncClient(timeout=20, proxy=proxy_url) as client:
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
        if platform == "instagram":
            # IG long-lived tokens are refreshed by calling /refresh_access_token
            # with the CURRENT long-lived token (we stash it in refresh_token
            # column since there's no separate refresh secret).
            r = await client.get(
                "https://graph.instagram.com/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": refresh_token,
                },
            )
            data = r.json() or {}
            new_token = data.get("access_token")
            return {
                "access_token": new_token,
                # Keep the newly-refreshed long-lived token as the "refresh"
                # source for the next rotation.
                "refresh_token": new_token or refresh_token,
                "expires_in": data.get("expires_in"),
                "raw": data,
            }
        # meta: no rotation
        return {"access_token": None, "refresh_token": refresh_token, "expires_in": None, "raw": {}}
