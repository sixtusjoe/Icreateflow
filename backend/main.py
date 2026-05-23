"""
ICREATEFLOW API — FastAPI backend for content scaling platform.
"""
import os
import sys
import shutil
import json
import secrets
import asyncio
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx
import database as db
from services import tiktok_scraper, ocr, generator, overlay, video
from services import openai_image
from services import oauth as oauth_svc
from services import audio_video as audio_video_svc
from services import clip_scheduler
from services.auth import hash_password, verify_password, create_access_token, decode_token

# --- App setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    Path("uploads").mkdir(exist_ok=True)
    Path("output").mkdir(exist_ok=True)
    Path("music").mkdir(exist_ok=True)
    # Kick off Clipping scheduler loops (slot planner / dispatcher / view poller)
    from services import clip_scheduler
    clip_tasks = await clip_scheduler.start_background_tasks()
    try:
        yield
    finally:
        for t in clip_tasks:
            t.cancel()

app = FastAPI(title="ICREATEFLOW API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _d in ["uploads", "output", "music"]:
    Path(_d).mkdir(exist_ok=True)

app.mount("/files/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/files/output", StaticFiles(directory="output"), name="output")
app.mount("/files/music", StaticFiles(directory="music"), name="music")


# --- Auth dependencies ---

async def get_current_user(request: Request):
    """Extract and validate JWT from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = auth[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")

    database = await db.get_db()
    try:
        user = await db.get_user(database, int(payload["sub"]))
        if not user:
            raise HTTPException(401, "User not found")
        status = dict(user).get("status")
        if status == "suspended":
            raise HTTPException(403, "Account suspended")
        if status == "pending":
            raise HTTPException(403, "Account pending admin approval")
        return dict(user)
    finally:
        await database.close()


async def admin_required(user: dict = Depends(get_current_user)):
    """Require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def _naive_utc_now() -> datetime:
    """Return UTC `now` as a tz-naive datetime.

    Several DB columns (e.g. `tiktok_consent_at`, `clip_posts.posted_at`)
    are `TIMESTAMP WITHOUT TIME ZONE`. asyncpg refuses to bind a tz-aware
    datetime into a naive column with a `can't subtract offset-naive and
    offset-aware datetimes` error. Stamp via this helper to keep the
    convention consistent across endpoints.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _ensure_fresh_account_token(
    database, account: dict, platform_name: str,
) -> Optional[str]:
    """Return a non-expired access token for `account[platform_name]_token`,
    refreshing via the saved refresh_token + admin OAuth app credentials
    when the stored token is within 2 minutes of expiry. Persists the
    refreshed token back to the row.

    Returns None if no token is connected; returns the existing token
    unchanged when no refresh is possible (no refresh_token, no admin
    creds, or refresh failed) so the caller can still attempt the call —
    the platform will 401 instead of us silently failing earlier.

    Used by both post_now (where it's now the same closure) and the
    refresh-account-profile endpoint (which previously read the raw
    stored token, hitting 401 the moment TT/YT short-lived tokens
    expired).
    """
    from services import oauth as oauth_svc  # local import to avoid cycles

    token_local = account.get(f"{platform_name}_token")
    if not token_local:
        return None
    exp = account.get(f"{platform_name}_expires_at")
    refresh = account.get(f"{platform_name}_refresh_token")
    needs_refresh = False
    if exp:
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=2):
                needs_refresh = True
        except Exception:
            pass
    if not needs_refresh or not refresh:
        return token_local

    cfg = await db.get_site_config(database)
    # facebook is provided by the meta OAuth app; instagram can come from
    # either the meta app (FB Login fan-out → sibling facebook_token
    # exists) or the standalone Instagram Login app.
    if platform_name == "facebook":
        provider = "meta"
    elif platform_name == "instagram":
        provider = "meta" if account.get("facebook_token") else "instagram"
    else:
        provider = platform_name
    cid = cfg.get(f"oauth_{provider}_client_id", "")
    csec = cfg.get(f"oauth_{provider}_client_secret", "")
    if not cid or not csec:
        return token_local
    try:
        refreshed = await oauth_svc.refresh_access_token(
            provider, refresh, cid, csec,
            proxy_url=account.get("proxy_url") or None,
        )
    except Exception:
        return token_local
    new_token = refreshed.get("access_token")
    if not new_token:
        return token_local
    updates_tok: dict = {f"{platform_name}_token": new_token}
    if refreshed.get("refresh_token"):
        updates_tok[f"{platform_name}_refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("expires_in"):
        new_exp = datetime.now(timezone.utc) + timedelta(seconds=int(refreshed["expires_in"]))
        updates_tok[f"{platform_name}_expires_at"] = new_exp.isoformat()
    try:
        await db.update_account(database, account["id"], **updates_tok)
    except Exception:
        pass
    return new_token


# Phone-grade device pool used for both slide EXIF (in serve_file_as_jpeg)
# and video container metadata (in _remux_video_with_account_metadata).
# Keeping one source of truth means the same account presents a coherent
# device identity across slides AND videos served on its behalf.
_DEVICE_POOL = [
    ("Apple",   "iPhone 15",       "17.5.1"),
    ("Apple",   "iPhone 14 Pro",   "17.6"),
    ("Apple",   "iPhone 13",       "18.0"),
    ("samsung", "SM-S928U",        "One UI 6.1"),  # Galaxy S24 Ultra
    ("samsung", "SM-S921U",        "One UI 6.0"),  # Galaxy S24
    ("Google",  "Pixel 8",         "TQ3A.230901.001"),
    ("Google",  "Pixel 7a",        "TQ3A.230705.001"),
]


async def _remux_video_with_account_metadata(src_path: Path, account_seed: int) -> bytes:
    """Return the input video re-muxed (no re-encode) with per-account
    container metadata so each account's API uploads carry a distinct
    fingerprint to TikTok / IG / FB / YouTube.

    Why this matters: the proxy work changes API origin IP, but every
    Brand account still served byte-identical .mp4s to platforms that
    PULL_FROM_URL (TikTok video, IG Reels) or that we fetch-then-upload
    (YouTube, Facebook). Identical bytes across accounts cluster as one
    operator regardless of the IP. Container metadata diversity (Make,
    Model, Software, creation_time, encoder, comment) is the cheap
    cousin of the slide EXIF work — runs `ffmpeg -c copy`, no quality
    loss, ~50–200ms for typical Shorts.

    `account_seed` is whatever stable id is the per-target granularity:
    Brand `accounts.id` for /posts/new, Clipping `artist_accounts.id`
    for the scheduler. Same seed → same device identity (cohesive
    "this account is one phone"); different seeds → different bytes.
    """
    make, model, software = _DEVICE_POOL[account_seed % len(_DEVICE_POOL)]
    # creation_time advances per request → breaks "same bytes across
    # repeat pulls" clustering. Recent past so it looks like a phone
    # capture.
    from random import randint
    shot = datetime.now(timezone.utc) - timedelta(seconds=randint(15 * 60, 6 * 3600))
    creation_time = shot.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    # Encoder string varies per make to look congruent.
    encoder_pool = {
        "Apple":   "HEVC",
        "samsung": "Lavf60.16.100",
        "Google":  "Lavf60.16.100",
    }
    encoder = encoder_pool[make]

    out_path = Path(f"/tmp/_remux_{account_seed}_{secrets.token_hex(4)}.mp4")
    cmd = [
        "ffmpeg", "-loglevel", "error", "-y",
        "-i", str(src_path),
        "-map_metadata", "-1",         # drop the source's metadata first
        "-c", "copy",                  # no re-encode
        "-movflags", "+faststart",     # phone-typical, also helps streaming
        "-metadata", f"creation_time={creation_time}",
        "-metadata", f"encoder={encoder}",
        "-metadata", f"make={make}",
        "-metadata", f"model={model}",
        "-metadata", f"software={software}",
        "-metadata", f"comment=IMG_{account_seed:04d}",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not out_path.exists():
        # Fail open — return raw bytes rather than 500 the caller. We'd
        # rather post with stale metadata than not post at all.
        with open(src_path, "rb") as f:
            return f.read()
    try:
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        try: out_path.unlink()
        except Exception: pass


async def verify_brand_ownership(brand_id: int, user: dict):
    """Check that brand belongs to user (admins can access all)."""
    database = await db.get_db()
    try:
        brand = await db.get_brand(database, brand_id)
        if not brand:
            raise HTTPException(404, "Brand not found")
        if brand["user_id"] != user["id"]:
            raise HTTPException(403, "Access denied")
        return dict(brand)
    finally:
        await database.close()


# --- Pydantic models ---

class AuthRegister(BaseModel):
    email: str
    password: str
    name: str

class AuthLogin(BaseModel):
    email: str
    password: str

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str

class RequestEmailChangeRequest(BaseModel):
    new_email: str

class ConfirmEmailChangeRequest(BaseModel):
    code: str

class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None
    name: Optional[str] = None

class BrandCreate(BaseModel):
    name: str
    slug: str
    background_color: str = "#000000"
    timezone: str = "US/Eastern"
    default_post_times: str = "09:00,13:00,18:00"

class BrandUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    background_color: Optional[str] = None
    timezone: Optional[str] = None
    default_post_times: Optional[str] = None

class AccountCreate(BaseModel):
    name: str
    role: str = "variation"
    tiktok_handle: Optional[str] = None
    youtube_handle: Optional[str] = None
    instagram_handle: Optional[str] = None
    facebook_handle: Optional[str] = None

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    tiktok_handle: Optional[str] = None
    youtube_handle: Optional[str] = None
    instagram_handle: Optional[str] = None
    facebook_handle: Optional[str] = None
    proxy_url: Optional[str] = None

class PostImport(BaseModel):
    tiktok_url: str
    brand_id: int
    caption: Optional[str] = None
    import_audio: bool = False
    audio_name: Optional[str] = None

class SlideUpdate(BaseModel):
    type: Optional[str] = None
    has_face: Optional[bool] = None
    title_text: Optional[str] = None
    body_text: Optional[str] = None
    cta_text: Optional[str] = None

class VariationUpdate(BaseModel):
    action: str = "keep"

class RegenerateSlide(BaseModel):
    account_id: int
    slide_number: int
    title_text: Optional[str] = None
    body_text: Optional[str] = None
    cta_text: Optional[str] = None
    font_size_title: Optional[int] = None
    font_size_body: Optional[int] = None
    font_size_cta: Optional[int] = None
    y_ratio_title: Optional[float] = None
    y_ratio_body: Optional[float] = None
    y_ratio_cta: Optional[float] = None
    x_ratio_title: Optional[float] = None   # 0.0 (far left) to 1.0 (far right), default 0.5
    x_ratio_body: Optional[float] = None
    x_ratio_cta: Optional[float] = None
    scale_title: Optional[float] = None     # Zoom multiplier on top of font_size (e.g. 1.0 = 100%)
    scale_body: Optional[float] = None
    scale_cta: Optional[float] = None
    font_weight: Optional[str] = None   # Light, Regular, Medium, SemiBold, Bold, ExtraBold, Black
    text_style: Optional[str] = None     # "stroke" or "background"

class FluxGenerate(BaseModel):
    prompt: str
    aspect_ratio: str = "3:4"
    use_reference: bool = True  # pass current slide image to OpenAI as reference

class PostSchedule(BaseModel):
    scheduled_time: Optional[str] = None
    caption: Optional[str] = None
    music_track_id: Optional[int] = None

class PostMusic(BaseModel):
    youtube_music_track_id: Optional[int] = None
    instagram_music_track_id: Optional[int] = None
    facebook_music_track_id: Optional[int] = None

class TikTokSettingsPayload(BaseModel):
    """TikTok Direct Post API settings, used both for per-(post, variation)
    `outputs` rows (Brand pipeline) and per-variation `artist_accounts`
    rows (Clipping pipeline).

    All fields optional — UI sends a partial PATCH on Save and stamps
    `tiktok_consent_at` server-side at the same moment (the music-usage
    acknowledgement). Privacy has no default value (TikTok rule).
    """
    tiktok_post_as_draft: Optional[bool] = None
    tiktok_privacy_level: Optional[str] = None
    tiktok_disclosure_enabled: Optional[bool] = None
    tiktok_disclose_your_brand: Optional[bool] = None
    tiktok_disclose_branded_content: Optional[bool] = None
    tiktok_allow_comment: Optional[bool] = None
    tiktok_allow_duet: Optional[bool] = None
    tiktok_allow_stitch: Optional[bool] = None

# Back-compat alias for the Brand outputs endpoint.
OutputTikTokSettings = TikTokSettingsPayload

class SettingUpdate(BaseModel):
    key: str
    value: str


# --- Clipping (Artists / Variations / Clips) ---

class ArtistCreate(BaseModel):
    name: str
    slug: str
    timezone: str = "US/Eastern"
    posts_per_day: int = 3
    window_start: str = "09:00"
    window_end: str = "21:00"


class ArtistUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    timezone: Optional[str] = None
    posts_per_day: Optional[int] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    gdrive_folder_url: Optional[str] = None


class VariationCreate(BaseModel):
    name: str
    tiktok_handle: Optional[str] = None
    youtube_handle: Optional[str] = None
    instagram_handle: Optional[str] = None
    facebook_handle: Optional[str] = None


class VariationUpdateArtist(BaseModel):
    name: Optional[str] = None
    tiktok_handle: Optional[str] = None
    youtube_handle: Optional[str] = None
    instagram_handle: Optional[str] = None
    facebook_handle: Optional[str] = None
    proxy_url: Optional[str] = None
    paused_reason: Optional[str] = None


class ClipUpdate(BaseModel):
    caption: Optional[str] = None


class GdriveSyncReq(BaseModel):
    folder_url: str


class PromotionStartReq(BaseModel):
    view_target: Optional[int] = None
    campaign_name: Optional[str] = None


class PromotionResetReq(BaseModel):
    view_target: Optional[int] = None
    campaign_name: Optional[str] = None
    delete_clips: bool = True


# --- Helper ---

def _tag_utc(d: dict) -> dict:
    """Tag naive timestamp columns as UTC so JSON serialization emits an
    offset — browsers then parse correctly rather than treating the string
    as local time. Stored values are always UTC."""
    for k in db._TIMESTAMP_COLUMNS:
        v = d.get(k)
        if isinstance(v, datetime) and v.tzinfo is None:
            d[k] = v.replace(tzinfo=timezone.utc)
    return d


def row_to_dict(row):
    if row is None:
        return None
    return _tag_utc(dict(row))

def rows_to_list(rows):
    return [_tag_utc(dict(r)) for r in rows]

def user_safe(user_dict: dict) -> dict:
    """Return user dict without password_hash."""
    d = dict(user_dict)
    d.pop("password_hash", None)
    return d


# =============================================
# AUTH ROUTES
# =============================================

@app.post("/api/auth/register")
async def register(data: AuthRegister):
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    database = await db.get_db()
    try:
        existing = await db.get_user_by_email(database, data.email.lower().strip())
        if existing:
            raise HTTPException(400, "Email already registered")

        pw_hash = hash_password(data.password)
        # New signups land in 'pending' — an admin must approve before they can log in.
        user_id = await db.create_user(
            database, data.email.lower().strip(), pw_hash, data.name.strip(),
            status="pending",
        )
        # Fire-and-forget welcome email
        import asyncio as _asyncio
        from services.email import send_welcome_pending_email as _send_welcome
        _asyncio.create_task(
            _send_welcome(data.email.lower().strip(), data.name.strip())
        )
        return {
            "pending": True,
            "message": "Your account is pending admin approval. You'll be able to log in once an admin approves you.",
        }
    finally:
        await database.close()


@app.post("/api/auth/login")
async def login(data: AuthLogin):
    database = await db.get_db()
    try:
        user = await db.get_user_by_email(database, data.email.lower().strip())
        if not user or not verify_password(data.password, user["password_hash"]):
            raise HTTPException(401, "Invalid email or password")
        if user["status"] == "suspended":
            raise HTTPException(403, "Account suspended")
        if user["status"] == "pending":
            raise HTTPException(403, "Your account is pending admin approval.")

        await db.update_user(database, user["id"], last_login=datetime.now(timezone.utc).isoformat())
        token = create_access_token(user["id"], user["email"], user["role"])
        return {"token": token, "user": user_safe(dict(user))}
    finally:
        await database.close()


@app.get("/api/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user_safe(user)


@app.put("/api/auth/profile")
async def update_profile(data: ProfileUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        updates = {}
        if data.name is not None:
            updates["name"] = data.name.strip()
        if data.email is not None:
            email = data.email.lower().strip()
            existing = await db.get_user_by_email(database, email)
            if existing and existing["id"] != user["id"]:
                raise HTTPException(400, "Email already taken")
            updates["email"] = email
        if updates:
            await db.update_user(database, user["id"], **updates)
        updated = await db.get_user(database, user["id"])
        return user_safe(dict(updated))
    finally:
        await database.close()


@app.put("/api/auth/password")
async def change_password(data: PasswordChange, user: dict = Depends(get_current_user)):
    if not verify_password(data.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if len(data.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    database = await db.get_db()
    try:
        await db.update_user(database, user["id"], password_hash=hash_password(data.new_password))
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/auth/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    """Generate and email a password reset OTP. Always returns ok=true (no email leak)."""
    from datetime import timedelta
    import secrets as _secrets
    try:
        from services.email import send_password_reset_email, generate_otp
    except ImportError:
        return {"ok": True}  # email not configured — silently succeed

    database = await db.get_db()
    try:
        email = data.email.lower().strip()
        user = await db.get_user_by_email(database, email)
        if user:
            otp = generate_otp(6)
            expires = datetime.now(timezone.utc) + timedelta(minutes=15)
            await database.execute(
                "INSERT INTO email_otps (user_id, email, code, purpose, expires_at) VALUES (?, ?, ?, 'password_reset', ?)",
                (user["id"], email, otp, expires),
            )
            await database.commit()
            # Fire and forget — don't block the response on SMTP
            import asyncio
            asyncio.create_task(send_password_reset_email(email, otp))
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/auth/reset-password")
async def reset_password(data: ResetPasswordRequest):
    """Validate OTP and set a new password."""
    database = await db.get_db()
    try:
        email = data.email.lower().strip()
        cur = await database.execute(
            "SELECT id, expires_at, used_at FROM email_otps WHERE email = ? AND code = ? AND purpose = 'password_reset' ORDER BY id DESC LIMIT 1",
            (email, data.code.strip()),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(400, "Invalid or expired code")
        rd = dict(row)
        if rd.get("used_at"):
            raise HTTPException(400, "Code already used")
        expires = rd["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(400, "Code has expired")
        if len(data.new_password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        user = await db.get_user_by_email(database, email)
        if not user:
            raise HTTPException(400, "User not found")
        await db.update_user(database, user["id"], password_hash=hash_password(data.new_password))
        await database.execute(
            "UPDATE email_otps SET used_at = ? WHERE id = ?",
            (datetime.now(timezone.utc), rd["id"]),
        )
        await database.commit()
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/users/me/request-email-change")
async def request_email_change(data: RequestEmailChangeRequest, user: dict = Depends(get_current_user)):
    """Send OTP to new_email to verify it before changing."""
    from datetime import timedelta
    try:
        from services.email import send_email_change_otp, generate_otp
    except ImportError:
        raise HTTPException(503, "Email service not available")

    database = await db.get_db()
    try:
        new_email = data.new_email.lower().strip()
        existing = await db.get_user_by_email(database, new_email)
        if existing and existing["id"] != user["id"]:
            raise HTTPException(400, "Email already taken")
        otp = generate_otp(6)
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        await database.execute(
            "INSERT INTO email_otps (user_id, email, code, purpose, new_email, expires_at) VALUES (?, ?, ?, 'email_change', ?, ?)",
            (user["id"], user["email"], otp, new_email, expires),
        )
        await database.commit()
        import asyncio
        asyncio.create_task(send_email_change_otp(user["email"], new_email, otp))
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/users/me/confirm-email-change")
async def confirm_email_change(data: ConfirmEmailChangeRequest, user: dict = Depends(get_current_user)):
    """Validate OTP and update the user's email."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT id, new_email, expires_at, used_at FROM email_otps WHERE user_id = ? AND code = ? AND purpose = 'email_change' ORDER BY id DESC LIMIT 1",
            (user["id"], data.code.strip()),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(400, "Invalid or expired code")
        rd = dict(row)
        if rd.get("used_at"):
            raise HTTPException(400, "Code already used")
        expires = rd["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(400, "Code has expired")
        new_email = rd["new_email"]
        existing = await db.get_user_by_email(database, new_email)
        if existing and existing["id"] != user["id"]:
            raise HTTPException(400, "Email already taken")
        await db.update_user(database, user["id"], email=new_email)
        await database.execute(
            "UPDATE email_otps SET used_at = ? WHERE id = ?",
            (datetime.now(timezone.utc), rd["id"]),
        )
        await database.commit()
        return {"ok": True}
    finally:
        await database.close()


@app.get("/api/public/config")
async def public_config():
    """Public endpoint — returns safe site config fields (logo, favicon, site name)."""
    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
        return {
            "site_logo_url": cfg.get("site_logo_url", ""),
            "site_favicon_url": cfg.get("site_favicon_url", ""),
            "site_name": cfg.get("site_name", "Icreateflow"),
        }
    finally:
        await database.close()


@app.get("/api/auth/unsubscribe")
async def unsubscribe_email(token: str):
    """One-click unsubscribe link — disables email notifications for the user."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT id FROM users WHERE unsubscribe_token = ?",
            (token,),
        )
        row = await cur.fetchone()
        if row:
            await database.execute(
                "UPDATE users SET email_notifications = 0 WHERE id = ?",
                (dict(row)["id"],),
            )
            await database.commit()
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;margin-top:60px'>"
            "<h2>You have been unsubscribed.</h2>"
            "<p>You will no longer receive email notifications from iCreateFlow.</p>"
            "</body></html>"
        )
    finally:
        await database.close()


# =============================================
# ADMIN ROUTES
# =============================================

@app.get("/api/admin/users")
async def admin_list_users(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        users = await db.get_users(database)
        return rows_to_list(users)
    finally:
        await database.close()


@app.post("/api/admin/users/{user_id}/approve")
async def admin_approve_user(user_id: int, admin: dict = Depends(admin_required)):
    """Approve a pending registration. Sets status='active' so the user can log in."""
    database = await db.get_db()
    try:
        user = await db.get_user(database, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        if dict(user).get("status") != "pending":
            raise HTTPException(400, "User is not pending approval")
        await db.update_user(database, user_id, status="active")
        updated = await db.get_user(database, user_id)
        return user_safe(dict(updated))
    finally:
        await database.close()


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, data: AdminUserUpdate, admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if updates:
            await db.update_user(database, user_id, **updates)
        user = await db.get_user(database, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        return user_safe(dict(user))
    finally:
        await database.close()


@app.get("/api/admin/site-config")
async def admin_get_site_config(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        return await db.get_site_config(database)
    finally:
        await database.close()


@app.put("/api/admin/site-config")
async def admin_update_site_config(data: SettingUpdate, admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        await db.set_site_config(database, data.key, data.value)
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/admin/send-test-email")
async def admin_send_test_email(admin: dict = Depends(admin_required)):
    """Send a test email to the logged-in admin's address to verify SMTP config."""
    try:
        from services.email import send_email
    except ImportError:
        raise HTTPException(500, "Email service not available — deploy email.py first")
    try:
        await send_email(
            to=admin["email"],
            subject="iCreateFlow — SMTP test email",
            html=(
                "<p>This is a test email from iCreateFlow.</p>"
                "<p>If you received this, your SMTP configuration is working correctly.</p>"
            ),
            text="This is a test email from iCreateFlow. SMTP is configured correctly.",
        )
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Failed to send test email: {exc}")


@app.post("/api/admin/upload-asset")
async def admin_upload_asset(
    type: str,  # "logo" or "favicon"
    file: UploadFile = File(...),
    admin: dict = Depends(admin_required),
):
    """Upload a logo or favicon image and store the URL in site_config."""
    if type not in ("logo", "favicon"):
        raise HTTPException(400, "type must be 'logo' or 'favicon'")
    allowed = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}
    if file.content_type not in allowed:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    asset_dir = Path("uploads") / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Determine extension
    ext_map = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/svg+xml": ".svg",
        "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
    }
    ext = ext_map.get(file.content_type, ".png")
    filename = f"{type}{ext}"
    dest = asset_dir / filename

    contents = await file.read()
    dest.write_bytes(contents)

    # Build the public URL — served via the existing /files/uploads static mount
    cfg = {}
    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
        base = cfg.get("oauth_redirect_base", "").rstrip("/") or ""
    finally:
        await database.close()

    file_url = f"{base}/files/uploads/assets/{filename}"

    # Save URL to site_config
    config_key = "site_logo_url" if type == "logo" else "site_favicon_url"
    database = await db.get_db()
    try:
        await db.set_site_config(database, config_key, file_url)
        await database.commit()
    finally:
        await database.close()

    return {"ok": True, "url": file_url}


def _dir_size_mb(path: str) -> float:
    total = 0
    p = Path(path)
    if not p.exists():
        return 0.0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024), 1)


@app.get("/api/admin/stats")
async def admin_stats(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        async def _count(sql: str) -> int:
            cur = await database.execute(sql)
            row = await cur.fetchone()
            return int(row["count"]) if row else 0

        total_users = await _count("SELECT COUNT(*) as count FROM users")
        total_brands = await _count("SELECT COUNT(*) as count FROM brands")
        total_posts = await _count("SELECT COUNT(*) as count FROM posts")
        total_tracks = await _count("SELECT COUNT(*) as count FROM music_tracks")
        total_accounts = await _count("SELECT COUNT(*) as count FROM accounts")
        total_artists = await _count("SELECT COUNT(*) as count FROM artists")
        total_variations = await _count("SELECT COUNT(*) as count FROM artist_accounts")
        total_clips = await _count("SELECT COUNT(*) as count FROM clips")
        total_clip_posts = await _count("SELECT COUNT(*) as count FROM clip_posts WHERE status = 'posted'")
        scheduled_posts = await _count(
            "SELECT COUNT(*) as count FROM posts WHERE status IN ('scheduled','generating','posting')"
        )
        failed_posts = await _count("SELECT COUNT(*) as count FROM posts WHERE status = 'failed'")
        suspended_users = await _count("SELECT COUNT(*) as count FROM users WHERE status = 'suspended'")
        pending_users = await _count("SELECT COUNT(*) as count FROM users WHERE status = 'pending'")

        # 24h activity
        new_users_24h = await _count(
            "SELECT COUNT(*) as count FROM users WHERE created_at > NOW() - INTERVAL '24 hours'"
        )
        new_posts_24h = await _count(
            "SELECT COUNT(*) as count FROM posts WHERE created_at > NOW() - INTERVAL '24 hours'"
        )

        # storage
        uploads_mb = _dir_size_mb("uploads")
        output_mb = _dir_size_mb("output")
        music_mb = _dir_size_mb("music")

        # system health (optional psutil)
        health: dict = {"cpu_percent": None, "mem_percent": None, "disk_percent": None}
        try:
            import psutil  # type: ignore
            health["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            health["mem_percent"] = psutil.virtual_memory().percent
            health["disk_percent"] = psutil.disk_usage("/").percent
        except Exception:
            pass

        return {
            "total_users": total_users,
            "total_brands": total_brands,
            "total_posts": total_posts,
            "total_tracks": total_tracks,
            "total_accounts": total_accounts,
            "total_artists": total_artists,
            "total_variations": total_variations,
            "total_clips": total_clips,
            "total_clip_posts": total_clip_posts,
            "scheduled_posts": scheduled_posts,
            "failed_posts": failed_posts,
            "suspended_users": suspended_users,
            "pending_users": pending_users,
            "new_users_24h": new_users_24h,
            "new_posts_24h": new_posts_24h,
            "storage_mb": {
                "uploads": uploads_mb,
                "output": output_mb,
                "music": music_mb,
                "total": round(uploads_mb + output_mb + music_mb, 1),
            },
            "health": health,
        }
    finally:
        await database.close()


@app.get("/api/admin/variation-health")
async def admin_variation_health(admin: dict = Depends(admin_required)):
    """Per-variation health diagnostics. is_healthy=False flags stale slots or
    incorrect directory_exhausted pauses (paused but unposted clips exist)."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            """
            SELECT
                aa.id,
                aa.name,
                aa.artist_id,
                aa.paused_reason,
                (SELECT COUNT(*) FROM clips c
                 WHERE c.artist_id = aa.artist_id
                   AND (c.artist_account_id = aa.id OR c.artist_account_id IS NULL)
                ) AS total_clips,
                (SELECT COUNT(*) FROM clips c
                 WHERE c.artist_id = aa.artist_id
                   AND (c.artist_account_id = aa.id OR c.artist_account_id IS NULL)
                   AND NOT EXISTS (
                       SELECT 1 FROM clip_posts cp
                       WHERE cp.clip_id = c.id
                         AND cp.status = 'posted'
                         AND cp.deleted_at IS NULL
                   )
                ) AS unposted_clips,
                (SELECT COUNT(*) FROM clip_posts cp
                 WHERE cp.artist_account_id = aa.id
                   AND cp.status = 'scheduled'
                ) AS scheduled_slots,
                (SELECT COUNT(*) FROM clip_posts cp
                 WHERE cp.artist_account_id = aa.id
                   AND cp.status = 'scheduled'
                   AND EXISTS (
                       SELECT 1 FROM clip_posts cp2
                       WHERE cp2.clip_id = cp.clip_id
                         AND cp2.status = 'posted'
                         AND cp2.deleted_at IS NULL
                   )
                   AND EXISTS (
                       SELECT 1 FROM clips c
                       WHERE c.artist_id = aa.artist_id
                         AND (c.artist_account_id = aa.id OR c.artist_account_id IS NULL)
                         AND NOT EXISTS (
                             SELECT 1 FROM clip_posts cp3
                             WHERE cp3.clip_id = c.id
                               AND cp3.status = 'posted'
                               AND cp3.deleted_at IS NULL
                         )
                   )
                ) AS stale_slots
            FROM artist_accounts aa
            ORDER BY aa.artist_id, aa.id
            """
        )
        rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            is_healthy = (
                d["stale_slots"] == 0
                and not (d["paused_reason"] == "directory_exhausted" and d["unposted_clips"] > 0)
            )
            result.append({**d, "is_healthy": is_healthy})
        return {"variations": result}
    finally:
        await database.close()


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, admin: dict = Depends(admin_required)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot delete yourself")
    database = await db.get_db()
    try:
        target = await db.get_user(database, user_id)
        if not target:
            raise HTTPException(404, "User not found")

        # Find and cascade-delete user's brands (cascades to accounts/posts/slides/variations/outputs)
        brands_cur = await database.execute("SELECT id FROM brands WHERE user_id = ?", (user_id,))
        for b in await brands_cur.fetchall():
            bid = b["id"]
            posts_cur = await database.execute("SELECT id FROM posts WHERE brand_id = ?", (bid,))
            for p in await posts_cur.fetchall():
                pid = p["id"]
                slides_cur = await database.execute("SELECT id FROM slides WHERE post_id = ?", (pid,))
                for s in await slides_cur.fetchall():
                    await database.execute("DELETE FROM variations WHERE slide_id = ?", (s["id"],))
                await database.execute("DELETE FROM slides WHERE post_id = ?", (pid,))
                await database.execute("DELETE FROM outputs WHERE post_id = ?", (pid,))
            await database.execute("DELETE FROM posts WHERE brand_id = ?", (bid,))
            await database.execute("DELETE FROM accounts WHERE brand_id = ?", (bid,))
        await database.execute("DELETE FROM brands WHERE user_id = ?", (user_id,))
        await database.execute("DELETE FROM music_tracks WHERE user_id = ?", (user_id,))
        await database.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        await database.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await database.commit()
        return {"ok": True}
    finally:
        await database.close()


# --- Admin cross-user resource management ---

@app.get("/api/admin/brands")
async def admin_list_brands(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """
            SELECT b.*, u.name AS user_name, u.email AS user_email,
                   (SELECT COUNT(*) FROM accounts a WHERE a.brand_id = b.id) AS account_count,
                   (SELECT COUNT(*) FROM posts p WHERE p.brand_id = b.id) AS post_count
            FROM brands b
            LEFT JOIN users u ON u.id = b.user_id
            ORDER BY b.created_at DESC
            """
        )
        return rows_to_list(await cursor.fetchall())
    finally:
        await database.close()


@app.delete("/api/admin/brands/{brand_id}")
async def admin_delete_brand(brand_id: int, admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        brand = await db.get_brand(database, brand_id)
        await db.delete_brand(database, brand_id)
    finally:
        await database.close()
    if brand and brand.get("slug"):
        for root in ("uploads", "output"):
            d = Path(root) / brand["slug"]
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@app.get("/api/admin/posts")
async def admin_list_posts(
    user_id: Optional[int] = None,
    brand_id: Optional[int] = None,
    status: Optional[str] = None,
    admin: dict = Depends(admin_required),
):
    database = await db.get_db()
    try:
        sql = """
            SELECT p.*, b.name AS brand_name, b.slug AS brand_slug,
                   u.id AS user_id, u.name AS user_name, u.email AS user_email
            FROM posts p
            JOIN brands b ON b.id = p.brand_id
            LEFT JOIN users u ON u.id = b.user_id
            WHERE 1=1
        """
        params: list = []
        if user_id:
            sql += " AND b.user_id = ?"
            params.append(user_id)
        if brand_id:
            sql += " AND p.brand_id = ?"
            params.append(brand_id)
        if status:
            sql += " AND p.status = ?"
            params.append(status)
        sql += " ORDER BY p.date DESC, p.post_number"
        cursor = await database.execute(sql, params)
        return rows_to_list(await cursor.fetchall())
    finally:
        await database.close()


@app.delete("/api/admin/posts/{post_id}")
async def admin_delete_post(post_id: int, admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        slides_cur = await database.execute("SELECT id FROM slides WHERE post_id = ?", (post_id,))
        for s in await slides_cur.fetchall():
            await database.execute("DELETE FROM variations WHERE slide_id = ?", (s["id"],))
        await database.execute("DELETE FROM slides WHERE post_id = ?", (post_id,))
        await database.execute("DELETE FROM outputs WHERE post_id = ?", (post_id,))
        await database.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await database.commit()
        return {"ok": True}
    finally:
        await database.close()


@app.get("/api/admin/accounts")
async def admin_list_accounts(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """
            SELECT a.*, b.name AS brand_name, b.slug AS brand_slug,
                   u.id AS user_id, u.name AS user_name, u.email AS user_email
            FROM accounts a
            JOIN brands b ON b.id = a.brand_id
            LEFT JOIN users u ON u.id = b.user_id
            ORDER BY b.name, a.role DESC, a.id
            """
        )
        return rows_to_list(await cursor.fetchall())
    finally:
        await database.close()


@app.get("/api/admin/music")
async def admin_list_music(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """
            SELECT m.*, u.name AS user_name, u.email AS user_email
            FROM music_tracks m
            LEFT JOIN users u ON u.id = m.user_id
            ORDER BY m.created_at DESC
            """
        )
        return rows_to_list(await cursor.fetchall())
    finally:
        await database.close()


@app.delete("/api/admin/music/{track_id}")
async def admin_delete_music(track_id: int, admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        await db.delete_music_track(database, track_id)
        return {"ok": True}
    finally:
        await database.close()


@app.get("/api/admin/schedule")
async def admin_list_schedule(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """
            SELECT p.*, b.name AS brand_name, b.slug AS brand_slug,
                   u.id AS user_id, u.name AS user_name
            FROM posts p
            JOIN brands b ON b.id = p.brand_id
            LEFT JOIN users u ON u.id = b.user_id
            WHERE p.status IN ('scheduled','generating','posting')
            ORDER BY p.date, p.scheduled_time
            """
        )
        return rows_to_list(await cursor.fetchall())
    finally:
        await database.close()


@app.get("/api/admin/api-keys")
async def admin_list_api_keys(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """
            SELECT u.id AS user_id, u.name AS user_name, u.email AS user_email,
                   MAX(CASE WHEN us.key = 'replicate_api_key' THEN us.value END) AS replicate,
                   MAX(CASE WHEN us.key IN ('anthropic_api_key','claude_api_key') THEN us.value END) AS anthropic
            FROM users u
            LEFT JOIN user_settings us ON us.user_id = u.id
            GROUP BY u.id, u.name, u.email
            ORDER BY u.id
            """
        )
        rows = []
        for r in await cursor.fetchall():
            d = dict(r)
            rep = d.pop("replicate") or ""
            ant = d.pop("anthropic") or ""
            d["has_replicate"] = bool(rep)
            d["has_anthropic"] = bool(ant)
            d["replicate_preview"] = (rep[:4] + "…" + rep[-4:]) if len(rep) > 8 else ""
            d["anthropic_preview"] = (ant[:6] + "…" + ant[-4:]) if len(ant) > 10 else ""
            rows.append(d)
        return rows
    finally:
        await database.close()


# --- OAuth app configuration (admin) ---

OAUTH_PLATFORMS = {"tiktok", "youtube", "meta", "instagram"}
OAUTH_CONFIG_KEYS = [
    "oauth_tiktok_client_id", "oauth_tiktok_client_secret",
    "oauth_youtube_client_id", "oauth_youtube_client_secret",
    "oauth_meta_client_id", "oauth_meta_client_secret",
    # Standalone Instagram API with Instagram Login (separate from Meta/FB app).
    "oauth_instagram_client_id", "oauth_instagram_client_secret",
    # Instagram webhook verify_token. Stored here so admins can paste it
    # into the Facebook developer console "Verify token" field; the same
    # value is checked when Facebook hits our callback URL with
    # ?hub.mode=subscribe&hub.verify_token=…&hub.challenge=… during
    # webhook subscription verification.
    "oauth_instagram_webhook_verify_token",
    "oauth_google_drive_api_key",
    "oauth_redirect_base",
]


class OAuthAppUpdate(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_key: Optional[str] = None
    redirect_base: Optional[str] = None
    tiktok_privacy_level: Optional[str] = None
    # Instagram-only: webhook subscription verify token. Returned in full
    # in the GET response (unlike client_secret which is masked) because
    # the admin needs to copy it into Facebook's developer console.
    webhook_verify_token: Optional[str] = None


def _mask(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s)
    return s[:4] + "…" + s[-4:] if len(s) > 8 else "…"


@app.get("/api/admin/oauth-apps")
async def admin_get_oauth_apps(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
        result = {
            "redirect_base": cfg.get("oauth_redirect_base", ""),
            "tiktok_privacy_level": cfg.get("tiktok_privacy_level", "SELF_ONLY"),
        }
        for platform in OAUTH_PLATFORMS:
            cid = cfg.get(f"oauth_{platform}_client_id", "")
            sec = cfg.get(f"oauth_{platform}_client_secret", "")
            entry = {
                "client_id": cid,
                "client_secret_preview": _mask(sec),
                "configured": bool(cid and sec),
            }
            if platform == "instagram":
                # Surface the full webhook verify token — admin needs to
                # copy it into the Facebook developer console UI. This is
                # admin-only data on an admin-only endpoint.
                entry["webhook_verify_token"] = cfg.get(
                    "oauth_instagram_webhook_verify_token", ""
                )
            result[platform] = entry
        gkey = cfg.get("oauth_google_drive_api_key", "")
        result["google_drive"] = {
            "api_key_preview": _mask(gkey),
            "configured": bool(gkey),
        }
        return result
    finally:
        await database.close()


@app.put("/api/admin/oauth-apps/{platform}")
async def admin_update_oauth_app(
    platform: str, data: OAuthAppUpdate, admin: dict = Depends(admin_required)
):
    if platform not in {"_base", "google_drive"} and platform not in OAUTH_PLATFORMS:
        raise HTTPException(400, f"Unknown platform: {platform}")
    database = await db.get_db()
    try:
        if platform == "_base":
            if data.redirect_base is not None:
                await db.set_site_config(database, "oauth_redirect_base", data.redirect_base)
        elif platform == "google_drive":
            if data.api_key is not None:
                await db.set_site_config(database, "oauth_google_drive_api_key", data.api_key)
        else:
            if data.client_id is not None:
                await db.set_site_config(database, f"oauth_{platform}_client_id", data.client_id)
            if data.client_secret is not None:
                await db.set_site_config(database, f"oauth_{platform}_client_secret", data.client_secret)
            if platform == "instagram" and data.webhook_verify_token is not None:
                # Empty string clears the token (disables webhook
                # verification); a non-empty value replaces what's stored.
                await db.set_site_config(
                    database,
                    "oauth_instagram_webhook_verify_token",
                    data.webhook_verify_token,
                )
            # Note: tiktok_privacy_level used to live in site_config as a
            # global default. Per TikTok's UX rules ("Users must manually
            # select the privacy status from a dropdown and there should
            # be no default value"), there can't be a global default —
            # privacy is now picked per-(post, variation) on the Brand
            # Generate tab and per-variation on the Clipping dashboard.
            # The old site_config row is left in place for back-compat
            # but is no longer read; admins can ignore it.
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# OAUTH CONNECT FLOWS (TikTok / YouTube / Meta)
# =============================================

# In-memory store of pending Meta OAuth grants awaiting variation→Page
# assignment. Keyed by a short-lived token returned to the popup; the popup
# posts the choice back through the parent window, which calls
# /api/oauth/meta/assign. Entries expire after 15 minutes (cleaned on each
# new write). Process-local: fine for single-worker dev; for multi-worker
# prod we'd swap to Redis or a DB row, but the assignment happens within
# seconds of the OAuth callback so a single worker is the realistic case.
_PENDING_META_ASSIGNMENTS: dict[str, dict] = {}


def _oauth_pick_asset_html(assign_token: str, assets: list[dict], target_id: int, kind: str) -> str:
    """Popup HTML that postMessages the asset list to the opener and closes.

    Frontend listens for `{type:'oauth', status:'pick_asset', ...}` and shows
    a modal letting the admin pick which Page/IG belongs to this variation.
    """
    import json as _json
    payload = _json.dumps({
        "type": "oauth",
        "status": "pick_asset",
        "assign_token": assign_token,
        "target_id": target_id,
        "kind": kind,
        "assets": assets,
    })
    return f"""<!doctype html><html><head><meta charset=utf-8><title>OAuth — pick page</title>
<style>body{{font-family:system-ui;background:#111;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}</style>
</head><body>
<div style="text-align:center">
  <h2>Connected!</h2>
  <p>Pick which Page belongs to this variation in the previous window…</p>
</div>
<script>
try {{
  if (window.opener) {{ window.opener.postMessage({payload}, '*'); }}
}} catch(e) {{}}
setTimeout(function(){{ try{{ window.close(); }}catch(e){{}} }}, 800);
</script>
</body></html>"""


def _oauth_finish(
    success: bool,
    message: str = "",
    *,
    flow: str = "popup",
    return_to: str = "",
    platform: str = "",
):
    """Render the appropriate end-of-OAuth response based on the flow.

    flow="popup" — return the close-html that postMessages the opener
        and auto-closes (existing behaviour).

    flow="redirect" — return 302 to `return_to` with query params
        oauth_status (success|error), oauth_platform, and oauth_message
        when there's a message to surface. Used by the standalone IG
        flow on mobile because iOS deep-links instagram.com/oauth into
        the IG app, breaking popup window.opener postMessage.

    Falls back to popup when flow=redirect but return_to is empty
    (defensive — shouldn't happen given the start-endpoint validation).
    """
    if flow == "redirect" and return_to:
        from urllib.parse import urlencode
        params = {
            "oauth_status": "success" if success else "error",
        }
        if platform:
            params["oauth_platform"] = platform
        if message:
            params["oauth_message"] = message[:200]
        sep = "&" if "?" in return_to else "?"
        return RedirectResponse(f"{return_to}{sep}{urlencode(params)}", status_code=302)
    return HTMLResponse(_oauth_close_html(success, message))


def _oauth_close_html(success: bool, message: str = "") -> str:
    status = "success" if success else "error"
    safe = message.replace("</", "<\\/").replace("'", "\\'")
    return f"""<!doctype html><html><head><meta charset=utf-8><title>OAuth {status}</title>
<style>body{{font-family:system-ui;background:#111;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}</style>
</head><body>
<div style="text-align:center">
  <h2>{'Connected!' if success else 'Connection failed'}</h2>
  <p>{safe or ('You can close this window.' if success else '')}</p>
</div>
<script>
try {{
  if (window.opener) {{
    window.opener.postMessage({{type:'oauth', status:'{status}', message:'{safe}'}}, '*');
  }}
}} catch(e) {{}}
setTimeout(function(){{ try{{ window.close(); }}catch(e){{}} }}, 800);
</script>
</body></html>"""


async def _verify_artist_ownership(artist_id: int, user: dict) -> dict:
    database = await db.get_db()
    try:
        artist = await db.get_artist(database, artist_id)
        if not artist:
            raise HTTPException(404, "Artist not found")
        if user.get("role") != "admin" and artist.get("user_id") != user["id"]:
            raise HTTPException(403, "Access denied")
        return dict(artist)
    finally:
        await database.close()


# --- TikTok creator_info passthrough ---
#
# TikTok requires the post-to-TikTok UI to query creator_info on render so
# the privacy dropdown options, interaction defaults, and creator-blocked
# state are fresh. This endpoint refreshes the access token for the row
# (Brand `accounts` or Clipping `artist_accounts`), calls the adapter's
# get_creator_info, and caches the result for 5 minutes per row to keep
# fiddly UI re-renders from blowing the rate limit.

_TIKTOK_CREATOR_INFO_CACHE: dict[tuple[str, int], tuple[datetime, dict]] = {}
_TIKTOK_CREATOR_INFO_TTL_SECONDS = 300


async def _refresh_tiktok_token_for_row(
    database, row: dict, kind: str, cfg: dict,
) -> Optional[str]:
    """Refresh `tiktok_token` on an accounts or artist_accounts row when
    near expiry. Returns the (possibly refreshed) access token, or None
    when no token / no refresh capability.

    Mirrors the in-closure refresher in `post_now` and the
    `_fresh_variation_token` in clip_scheduler — kept here so the
    creator-info endpoint can serve both pipelines without circular
    imports.
    """
    token_local = row.get("tiktok_token")
    if not token_local:
        return None
    exp = row.get("tiktok_expires_at")
    refresh = row.get("tiktok_refresh_token")
    needs_refresh = False
    if exp:
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=2):
                needs_refresh = True
        except Exception:
            pass
    if not needs_refresh or not refresh:
        return token_local
    cid = cfg.get("oauth_tiktok_client_id", "")
    csec = cfg.get("oauth_tiktok_client_secret", "")
    if not cid or not csec:
        return token_local
    try:
        refreshed = await oauth_svc.refresh_access_token("tiktok", refresh, cid, csec)
    except Exception:
        return token_local
    new_token = refreshed.get("access_token")
    if not new_token:
        return token_local
    updates: dict = {"tiktok_token": new_token}
    if refreshed.get("refresh_token"):
        updates["tiktok_refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("expires_in"):
        new_exp = datetime.now(timezone.utc) + timedelta(seconds=int(refreshed["expires_in"]))
        updates["tiktok_expires_at"] = new_exp.isoformat()
    try:
        if kind == "variation":
            await db.update_artist_account(database, row["id"], **updates)
        else:
            await db.update_account(database, row["id"], **updates)
    except Exception:
        pass
    return new_token


@app.get("/api/oauth/tiktok/creator-info")
async def tiktok_creator_info(
    account_id: int,
    kind: str = "variation",
    user: dict = Depends(get_current_user),
):
    """Fetch TikTok creator_info for either a Brand account or a Clipping
    variation. Required by TikTok's UX rules — the post-to-TikTok page
    MUST call this on render to populate the privacy dropdown options,
    surface the creator's nickname, and detect creator-blocked state.

    Cached for 5 minutes per row. The UI invalidates by passing
    `?refresh=1` (TODO if needed); current callers tolerate the TTL.
    """
    if kind not in ("variation", "brand_account"):
        raise HTTPException(400, "kind must be 'variation' or 'brand_account'")

    cache_key = (kind, account_id)
    cached = _TIKTOK_CREATOR_INFO_CACHE.get(cache_key)
    now = datetime.now(timezone.utc)
    if cached and cached[0] > now:
        return cached[1]

    database = await db.get_db()
    try:
        if kind == "variation":
            row = await db.get_artist_account(database, account_id)
            if not row:
                raise HTTPException(404, "Variation not found")
            await _verify_artist_ownership(row["artist_id"], user)
            row_d = dict(row)
            proxy_url = row_d.get("proxy_url") or None
        else:
            row = await db.get_account(database, account_id)
            if not row:
                raise HTTPException(404, "Account not found")
            row_d = dict(row)
            # Brand account ownership: the brand's owning user must match.
            brand = await db.get_brand(database, row_d.get("brand_id"))
            if not brand:
                raise HTTPException(404, "Brand not found")
            if user.get("role") != "admin" and brand.get("user_id") != user["id"]:
                raise HTTPException(403, "Access denied")
            proxy_url = None

        cfg = await db.get_site_config(database)
        token = await _refresh_tiktok_token_for_row(database, row_d, kind, cfg)
        if not token:
            raise HTTPException(409, "TikTok is not connected on this account")

        from services.posting.tiktok import get_creator_info as _get_creator_info
        from services.posting import TikTokCreatorBlocked as _TikTokCreatorBlocked
        try:
            data = await _get_creator_info(token, proxy_url=proxy_url)
        except _TikTokCreatorBlocked as e:
            # 423 Locked is a closer fit than 4xx-Bad-Request for "the
            # creator can't post right now". The UI renders a clear
            # try-again-later block.
            return JSONResponse(
                status_code=423,
                content={"detail": str(e), "creator_blocked": True},
            )
    finally:
        await database.close()

    expires = now + timedelta(seconds=_TIKTOK_CREATOR_INFO_TTL_SECONDS)
    _TIKTOK_CREATOR_INFO_CACHE[cache_key] = (expires, data)
    return data


@app.get("/api/oauth/{platform}/start")
async def oauth_start(
    platform: str,
    account_id: Optional[int] = None,
    variation_id: Optional[int] = None,
    flow: str = "popup",
    return_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if platform not in oauth_svc.AUTHORIZE_URLS:
        raise HTTPException(400, f"Unknown platform: {platform}")
    if (account_id is None) == (variation_id is None):
        raise HTTPException(400, "Pass exactly one of account_id or variation_id")
    if flow not in ("popup", "redirect"):
        raise HTTPException(400, "flow must be 'popup' or 'redirect'")
    # Defense-in-depth: only accept return_to within our own configured
    # public base, so a malicious caller can't turn this endpoint into
    # an open-redirector.
    if flow == "redirect" and return_to and not return_to.startswith("/"):
        raise HTTPException(400, "return_to must be a same-site path (e.g. '/brands')")

    kind = "account" if account_id is not None else "variation"
    target_id = account_id if account_id is not None else variation_id

    database = await db.get_db()
    try:
        if kind == "account":
            row = await db.get_account(database, target_id)
            if not row:
                raise HTTPException(404, "Account not found")
            await verify_brand_ownership(row["brand_id"], user)
        else:
            row = await db.get_artist_account(database, target_id)
            if not row:
                raise HTTPException(404, "Variation not found")
            await _verify_artist_ownership(row["artist_id"], user)
        cfg = await db.get_site_config(database)
    finally:
        await database.close()

    redirect_base = cfg.get("oauth_redirect_base", "")
    # "instagram" tile: prefer the standalone Instagram Login app; fall back to
    # the Meta FB-Login app if admin hasn't configured the IG app yet. This
    # keeps existing Meta-only setups working while enabling users to connect
    # IG without Facebook once the IG app is configured.
    effective_platform = platform
    if platform == "instagram" and not cfg.get("oauth_instagram_client_id"):
        effective_platform = "meta"

    client_id = cfg.get(f"oauth_{effective_platform}_client_id", "")
    if not client_id or not redirect_base:
        raise HTTPException(400, f"{platform} OAuth app not configured by admin")

    redirect_uri = oauth_svc.build_redirect_uri(redirect_base, effective_platform)

    # The Meta flow renders an asset-picker HTML page in the popup that
    # postMessages the chosen Page back to the opener — that requires
    # popup mode. If the caller asked for redirect but we resolved to
    # meta (FB-Login fallback when no standalone IG app is configured),
    # downgrade to popup so the asset picker keeps working.
    effective_flow = flow
    if effective_platform == "meta":
        effective_flow = "popup"

    state = oauth_svc.sign_state(
        user["id"], target_id, effective_platform,
        kind=kind, flow=effective_flow, return_to=return_to,
    )
    auth_url = oauth_svc.build_authorize_url(effective_platform, client_id, redirect_uri, state)
    return {"authorize_url": auth_url, "flow": effective_flow}


@app.get("/api/oauth/{platform}/callback")
async def oauth_callback(
    platform: str,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    # Instagram webhook subscription verification. Facebook GETs this URL
    # with ?hub.mode=subscribe&hub.verify_token=…&hub.challenge=… when
    # the operator saves the webhook config in the developer console.
    # We must echo `hub.challenge` as plain text only when `hub.verify_token`
    # matches the stored secret, otherwise return 403. The dotted query
    # keys can't be bound as typed function args, so we read them off
    # request.query_params.
    qp = request.query_params
    if platform == "instagram" and qp.get("hub.mode") == "subscribe":
        token_provided = qp.get("hub.verify_token") or ""
        challenge = qp.get("hub.challenge") or ""
        database = await db.get_db()
        try:
            cfg = await db.get_site_config(database)
            token_stored = cfg.get("oauth_instagram_webhook_verify_token") or ""
        finally:
            await database.close()
        if not token_stored:
            raise HTTPException(503, "Webhook verify token not configured")
        if token_provided != token_stored:
            raise HTTPException(403, "verify_token mismatch")
        return Response(content=challenge, media_type="text/plain")

    # Decode state preemptively (best-effort — even when later validation
    # fails) so we know whether to render the close-html (popup flow) or
    # 302 back to the caller's page (redirect flow). Provider error
    # callbacks still carry our state token, so we can route most error
    # cases to the right shape too.
    pre_verified = oauth_svc.verify_state(state) if state else None
    early_flow = (pre_verified or {}).get("flow") or "popup"
    early_return_to = (pre_verified or {}).get("return_to") or ""

    if error:
        return _oauth_finish(
            False, f"Provider error: {error}",
            flow=early_flow, return_to=early_return_to, platform=platform,
        )
    if platform not in oauth_svc.AUTHORIZE_URLS:
        return _oauth_finish(
            False, "Unknown platform",
            flow=early_flow, return_to=early_return_to, platform=platform,
        )
    if not code or not state:
        return _oauth_finish(
            False, "Missing code or state",
            flow=early_flow, return_to=early_return_to, platform=platform,
        )

    verified = pre_verified
    if not verified or verified["platform"] != platform:
        return _oauth_finish(
            False, "Invalid or expired state",
            flow=early_flow, return_to=early_return_to, platform=platform,
        )

    target_id = verified["account_id"]
    kind = verified.get("kind", "account")
    flow = verified.get("flow") or "popup"
    return_to = verified.get("return_to") or ""

    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
        client_id = cfg.get(f"oauth_{platform}_client_id", "")
        client_secret = cfg.get(f"oauth_{platform}_client_secret", "")
        redirect_base = cfg.get("oauth_redirect_base", "")
        redirect_uri = oauth_svc.build_redirect_uri(redirect_base, platform)

        try:
            tokens = await oauth_svc.exchange_code(platform, code, client_id, client_secret, redirect_uri)
        except Exception as e:
            return _oauth_finish(
                False, f"Token exchange failed: {e}",
                flow=flow, return_to=return_to, platform=platform,
            )

        if not tokens.get("access_token"):
            return _oauth_finish(
                False, "Provider returned no access token",
                flow=flow, return_to=return_to, platform=platform,
            )

        expires_at = None
        if tokens.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tokens["expires_in"]))
            expires_at = expires_at.isoformat()

        # =====================================================================
        # Meta multi-asset flow: a single OAuth grant can authorize multiple
        # Pages + IG accounts. Don't write to the variation here — fetch the
        # full asset list, stash it under a short-lived token, and tell the
        # popup to ask the admin which asset belongs to this variation. The
        # frontend then POSTs to /api/oauth/meta/assign with the chosen page.
        # =====================================================================
        if platform == "meta":
            try:
                assets = await oauth_svc.fetch_meta_assets(tokens["access_token"])
            except Exception as e:
                return _oauth_finish(
                    False, f"Asset discovery failed: {e}",
                    flow=flow, return_to=return_to, platform=platform,
                )
            if not assets:
                return _oauth_finish(
                    False,
                    "No Pages or Instagram accounts were granted. Reconnect and tick at least one Page or IG.",
                    flow=flow, return_to=return_to, platform=platform,
                )
            assign_token = secrets.token_urlsafe(24)
            payload_json = json.dumps({
                "user_token": tokens["access_token"],
                "user_token_expires_at": expires_at,
                "scope": tokens.get("scope"),
                "assets": assets,
                "target_id": target_id,
                "kind": kind,
            })
            # Persist to DB so the assign POST (which may land on a different
            # gunicorn worker) can find it. Was an in-memory dict; under
            # `-w 2` workers the assign endpoint hit a different worker ~50%
            # of the time and returned 404.
            db_assign = await db.get_db()
            try:
                await db_assign.execute(
                    "INSERT INTO meta_pending_assignments (token, payload) VALUES (?, ?)",
                    (assign_token, payload_json),
                )
                # Drop expired entries opportunistically (>15 min old).
                await db_assign.execute(
                    "DELETE FROM meta_pending_assignments "
                    "WHERE created_at < NOW() - INTERVAL '15 minutes'"
                )
                await db_assign.commit()
            finally:
                await db_assign.close()
            return HTMLResponse(_oauth_pick_asset_html(assign_token, assets, target_id, kind))

        # ========== non-Meta platforms keep the original direct-write flow ==========
        target_platforms = [platform]
        updates: dict = {}
        for p in target_platforms:
            updates[f"{p}_token"] = tokens["access_token"]
            if tokens.get("refresh_token"):
                updates[f"{p}_refresh_token"] = tokens["refresh_token"]
            if expires_at:
                updates[f"{p}_expires_at"] = expires_at
            if tokens.get("scope"):
                updates[f"{p}_scopes"] = tokens["scope"]
            if tokens.get("platform_user_id"):
                updates[f"{p}_user_id"] = str(tokens["platform_user_id"])

        # Use the strict variant so failures land in error_logs. The
        # tile would otherwise show "Connected" with no @handle and we'd
        # have no signal from /admin → Errors about why. The strict call
        # only raises ProfileFetchError; we still swallow it so a
        # handle-lookup blip doesn't fail the whole OAuth (tokens are
        # already persisted below — the user can hit the refresh icon
        # on the account row to re-fetch).
        try:
            # For standalone Instagram OAuth the token exchange already
            # returns the IG user id; pass it so the profile fetch uses
            # GET /{ig_user_id} instead of GET /me (which now 400s).
            _ig_id = tokens.get("platform_user_id") if platform == "instagram" else None
            handles = await oauth_svc.fetch_profile_handles_strict(
                platform, tokens["access_token"], prefer_ig_id=_ig_id
            )
            for k, v in (handles or {}).items():
                if v:
                    updates[k] = v
        except oauth_svc.ProfileFetchError as e:
            await db.log_error(
                database, source=f"oauth.profile.{platform}",
                message=f"OAuth callback handle fetch: {str(e)[:300]}",
                context=f"target_id={target_id} kind={kind}",
            )
        except Exception as e:
            await db.log_error(
                database, source=f"oauth.profile.{platform}",
                message=f"OAuth callback handle fetch: {type(e).__name__}: {str(e)[:300]}",
                context=f"target_id={target_id} kind={kind}",
            )

        if kind == "variation":
            await db.update_artist_account(database, target_id, **updates)
        else:
            await db.update_account(database, target_id, **updates)
        return _oauth_finish(
            True, flow=flow, return_to=return_to, platform=platform,
        )
    finally:
        await database.close()


class MetaAssignAsset(BaseModel):
    assign_token: str
    page_id: Optional[str] = None  # Page-based: gets FB Page + linked IG
    ig_user_id: Optional[str] = None  # Standalone IG (no Page) fallback


@app.post("/api/oauth/meta/assign")
async def oauth_meta_assign(payload: MetaAssignAsset, user: dict = Depends(get_current_user)):
    """Finalize a Meta OAuth grant by assigning a chosen Page/IG to the
    variation/account that initiated the connect. Called by the frontend
    after the popup posts the asset list.
    """
    db_pop = await db.get_db()
    try:
        # The DB wrapper doesn't surface rows from DELETE ... RETURNING — it
        # only handles INSERT/UPDATE returning. So SELECT first, then DELETE.
        cur = await db_pop.execute(
            "SELECT payload FROM meta_pending_assignments WHERE token = ? "
            "AND created_at >= NOW() - INTERVAL '15 minutes'",
            (payload.assign_token,),
        )
        row = await cur.fetchone()
        if row:
            await db_pop.execute(
                "DELETE FROM meta_pending_assignments WHERE token = ?",
                (payload.assign_token,),
            )
            await db_pop.commit()
    finally:
        await db_pop.close()
    if not row:
        raise HTTPException(404, "Assignment expired or unknown — reconnect")
    pending = json.loads(row["payload"])

    target_id = pending["target_id"]
    kind = pending["kind"]
    assets = pending["assets"]
    user_token = pending["user_token"]
    user_token_expires_at = pending.get("user_token_expires_at")

    # Find the chosen asset by id (page first, IG fallback for standalone case).
    chosen = None
    if payload.page_id:
        chosen = next((a for a in assets if a.get("page_id") == payload.page_id), None)
    if not chosen and payload.ig_user_id:
        chosen = next((a for a in assets if a.get("ig_user_id") == payload.ig_user_id), None)
    if not chosen:
        raise HTTPException(400, "Selected asset not in the granted set")

    # Build column updates. The Page access token replaces facebook_token so
    # downstream posting uses a long-lived Page token. We also stash the
    # long-lived USER token in facebook_refresh_token / instagram_refresh_token
    # so we can re-exchange it before its 60d window closes (handled by the
    # token refresh path).
    updates: dict = {}
    if chosen.get("page_id"):
        if chosen.get("page_access_token"):
            updates["facebook_token"] = chosen["page_access_token"]
        updates["facebook_user_id"] = chosen["page_id"]
        if chosen.get("page_name"):
            updates["facebook_handle"] = chosen["page_name"]
        # Stash long-lived user token for future Page-token re-mints / refreshes.
        updates["facebook_refresh_token"] = user_token
        if user_token_expires_at:
            updates["facebook_expires_at"] = user_token_expires_at
    if chosen.get("ig_user_id"):
        # IG Business posts via the same FB Page token, so reuse it.
        if chosen.get("page_access_token"):
            updates["instagram_token"] = chosen["page_access_token"]
        elif user_token:
            updates["instagram_token"] = user_token
        updates["instagram_user_id"] = chosen["ig_user_id"]
        if chosen.get("ig_handle"):
            updates["instagram_handle"] = chosen["ig_handle"]
        updates["instagram_refresh_token"] = user_token
        if user_token_expires_at:
            updates["instagram_expires_at"] = user_token_expires_at

    database = await db.get_db()
    try:
        if kind == "variation":
            await db.update_artist_account(database, target_id, **updates)
        else:
            await db.update_account(database, target_id, **updates)
        return {"ok": True, "assigned": {
            "page_id": chosen.get("page_id"),
            "page_name": chosen.get("page_name"),
            "ig_user_id": chosen.get("ig_user_id"),
            "ig_handle": chosen.get("ig_handle"),
        }}
    finally:
        await database.close()


@app.post("/api/oauth/{platform}/disconnect")
async def oauth_disconnect(
    platform: str,
    account_id: Optional[int] = None,
    variation_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    if platform not in ("tiktok", "youtube", "instagram", "facebook", "meta"):
        raise HTTPException(400, f"Unknown platform: {platform}")
    if (account_id is None) == (variation_id is None):
        raise HTTPException(400, "Pass exactly one of account_id or variation_id")

    database = await db.get_db()
    try:
        target_platforms = ["instagram", "facebook"] if platform == "meta" else [platform]
        updates: dict = {}
        for p in target_platforms:
            updates[f"{p}_token"] = None
            updates[f"{p}_refresh_token"] = None
            updates[f"{p}_expires_at"] = None
            updates[f"{p}_scopes"] = None
            updates[f"{p}_user_id"] = None
            # Clear the auto-populated handle too — it was pulled from the
            # connected profile, so disconnecting should wipe it. Users who
            # typed a handle manually can re-enter it via the Edit button.
            updates[f"{p}_handle"] = ""

        if account_id is not None:
            row = await db.get_account(database, account_id)
            if not row:
                raise HTTPException(404, "Account not found")
            await verify_brand_ownership(row["brand_id"], user)
            await db.update_account(database, account_id, **updates)
        else:
            row = await db.get_artist_account(database, variation_id)
            if not row:
                raise HTTPException(404, "Variation not found")
            await _verify_artist_ownership(row["artist_id"], user)
            await db.update_artist_account(database, variation_id, **updates)
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# BRAND ROUTES (user-scoped)
# =============================================

@app.post("/api/brands")
async def create_brand(data: BrandCreate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        try:
            # Auto-uniquify the slug. brands.slug is globally unique (used
            # in URL routing), so a typed slug that collides — even with
            # another tenant's brand — would error out. Walk -2, -3, …
            # until we find a free one. We pass the resolved slug back so
            # the frontend can surface it if it differs from the input.
            from sqlalchemy import select as _sel
            from database import Brand as _Brand
            base_slug = data.slug
            slug = base_slug
            for n in range(2, 200):
                exists = (await database.session.execute(
                    _sel(_Brand.id).where(_Brand.slug == slug)
                )).scalar_one_or_none()
                if exists is None:
                    break
                slug = f"{base_slug}-{n}"
            else:
                raise HTTPException(
                    409,
                    f"Couldn't find a free slug variant of '{base_slug}' after "
                    f"200 attempts. Pick a more distinctive name.",
                )

            brand_id = await db.create_brand(
                database, data.name, slug,
                data.background_color, data.timezone, data.default_post_times,
                user_id=user["id"]
            )
            brand = await db.get_brand(database, brand_id)
            return row_to_dict(brand)
        except HTTPException:
            raise
        except Exception as e:
            # Log full traceback so the operator sees it in /admin → Errors,
            # and surface a useful detail to the client toast (the previous
            # generic 500 made this user-blocking bug invisible).
            await db.log_error(
                database, source="api",
                message=f"POST /api/brands name={data.name!r} slug={data.slug!r}: {e}",
                traceback=traceback.format_exc(),
                user_id=user.get("id"),
            )
            raise HTTPException(
                500,
                f"Create brand failed: {str(e)[:160]} (see /admin → Errors for full traceback)",
            )
    finally:
        await database.close()

@app.get("/api/brands")
async def list_brands(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        brands = await db.get_brands(database, user_id=user["id"])
        result = []
        for b in brands:
            brand_dict = dict(b)
            accounts = await db.get_accounts(database, b["id"])
            brand_dict["accounts"] = rows_to_list(accounts)
            result.append(brand_dict)
        return result
    finally:
        await database.close()

@app.get("/api/brands/{brand_id}")
async def get_brand(brand_id: int, user: dict = Depends(get_current_user)):
    brand = await verify_brand_ownership(brand_id, user)
    database = await db.get_db()
    try:
        accounts = await db.get_accounts(database, brand_id)
        brand["accounts"] = rows_to_list(accounts)
        return brand
    finally:
        await database.close()

@app.put("/api/brands/{brand_id}")
async def update_brand(brand_id: int, data: BrandUpdate, user: dict = Depends(get_current_user)):
    await verify_brand_ownership(brand_id, user)
    database = await db.get_db()
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if updates:
            await db.update_brand(database, brand_id, **updates)
        brand = await db.get_brand(database, brand_id)
        return row_to_dict(brand)
    finally:
        await database.close()

@app.delete("/api/brands/{brand_id}")
async def delete_brand(brand_id: int, user: dict = Depends(get_current_user)):
    await verify_brand_ownership(brand_id, user)
    database = await db.get_db()
    try:
        brand = await db.get_brand(database, brand_id)
        await db.delete_brand(database, brand_id)
    finally:
        await database.close()
    # Wipe disk artifacts too — DB cascade alone leaves these orphaned
    # forever. uploads/ holds the original slide sources; output/ holds
    # the generated renders. Both are tied 1:1 to this brand's slug.
    if brand and brand.get("slug"):
        for root in ("uploads", "output"):
            d = Path(root) / brand["slug"]
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


# =============================================
# ACCOUNT ROUTES (user-scoped via brand)
# =============================================

@app.post("/api/brands/{brand_id}/accounts")
async def create_account(brand_id: int, data: AccountCreate, user: dict = Depends(get_current_user)):
    await verify_brand_ownership(brand_id, user)
    database = await db.get_db()
    try:
        kwargs = {k: v for k, v in data.model_dump().items() if v is not None and k not in ("name", "role")}
        account_id = await db.create_account(database, brand_id, data.name, data.role, **kwargs)
        account = await db.get_account(database, account_id)
        return row_to_dict(account)
    finally:
        await database.close()

@app.put("/api/accounts/{account_id}")
async def update_account(account_id: int, data: AccountUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        account = await db.get_account(database, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        await verify_brand_ownership(account["brand_id"], user)
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if updates:
            await db.update_account(database, account_id, **updates)
        account = await db.get_account(database, account_id)
        return row_to_dict(account)
    finally:
        await database.close()

@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        account = await db.get_account(database, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        await verify_brand_ownership(account["brand_id"], user)
        await db.delete_account(database, account_id)
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/accounts/{account_id}/refresh-profile")
async def refresh_account_profile(account_id: int, user: dict = Depends(get_current_user)):
    """Re-run profile handle lookup for every connected platform on a brand
    account. Mirrors /api/variations/{id}/refresh-profile for artist-variations.
    """
    database = await db.get_db()
    try:
        row = await db.get_account(database, account_id)
        if not row:
            raise HTTPException(404, "Account not found")
        await verify_brand_ownership(row["brand_id"], user)
        a = dict(row)

        status: dict[str, dict] = {}
        updates: dict = {}
        # (token_field, api_platform, display_key)
        # `api_platform` is what fetch_profile_handles_strict expects:
        # the Meta-owned Facebook+linked-IG flow uses the "meta" lookup;
        # the standalone Instagram Login app uses the "instagram" lookup
        # (a separate /me endpoint on graph.instagram.com). When both
        # facebook_token and instagram_token are present (Meta-flow IG),
        # the meta lookup returns both handles in one call so we only
        # need the standalone-IG path when `instagram_token` exists
        # WITHOUT `facebook_token`.
        platform_specs: list[tuple[str, str, str]] = [
            ("tiktok",   "tiktok",  "tiktok"),
            ("youtube",  "youtube", "youtube"),
            ("facebook", "meta",    "facebook"),
        ]
        if a.get("instagram_token") and not a.get("facebook_token"):
            platform_specs.append(("instagram", "instagram", "instagram"))
        for token_field, api_platform, display_key in platform_specs:
            if not a.get(token_field):
                status[display_key] = {"status": "skipped", "reason": "not connected"}
                continue
            # CRITICAL: refresh the token before calling the platform —
            # TT (24h) and YT (1h) tokens expire frequently and the
            # previous code called fetch_profile_handles_strict with
            # whatever raw token was in the DB, getting 401s.
            try:
                token = await _ensure_fresh_account_token(database, a, token_field)
            except Exception as e:
                status[display_key] = {"status": "failed", "error": f"refresh: {type(e).__name__}: {str(e)[:200]}"}
                continue
            if not token:
                status[display_key] = {"status": "skipped", "reason": "not connected"}
                continue
            try:
                handles = await oauth_svc.fetch_profile_handles_strict(api_platform, token)
                if handles:
                    updates.update(handles)
                    status[display_key] = {"status": "ok", "handles": handles}
                else:
                    status[display_key] = {"status": "empty", "reason": "no username returned"}
            except oauth_svc.ProfileFetchError as e:
                msg = str(e)[:300]
                status[display_key] = {"status": "failed", "error": msg}
                await db.log_error(
                    database, source=f"oauth.profile.{api_platform}",
                    message=msg, context=f"account_id={account_id}",
                )
            except Exception as e:
                status[display_key] = {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:250]}"}

        if updates:
            await db.update_account(database, account_id, **updates)
        return {"account_id": account_id, "results": status}
    finally:
        await database.close()


# =============================================
# POST ROUTES (user-scoped via brand)
# =============================================

@app.get("/api/posts")
async def list_posts(brand_id: Optional[int] = None, date: Optional[str] = None, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        posts = await db.get_posts(database, brand_id=brand_id, date=date, user_id=user["id"])
        # Build a brand-id → name lookup so we can include brand_name in each post
        brands = await db.get_brands(database, user_id=user["id"])
        brand_names = {b["id"]: b["name"] for b in brands}
        result = []
        for p in posts:
            post_dict = dict(p)
            post_dict["brand_name"] = brand_names.get(p["brand_id"], "")
            slides = await db.get_slides(database, p["id"])
            post_dict["slides"] = rows_to_list(slides)
            post_dict["slide_count"] = len(slides)
            result.append(post_dict)
        return result
    finally:
        await database.close()

@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")

        # Verify ownership
        brand = await db.get_brand(database, post["brand_id"])
        if user["role"] != "admin" and brand and brand["user_id"] != user["id"]:
            raise HTTPException(403, "Access denied")

        result = dict(post)
        slides = await db.get_slides(database, post_id)
        result["slides"] = []

        for s in slides:
            slide_dict = dict(s)
            cursor = await database.execute(
                "SELECT * FROM variations WHERE slide_id = ? ORDER BY account_id", (s["id"],)
            )
            variations = await cursor.fetchall()
            slide_dict["variations"] = rows_to_list(variations)
            result["slides"].append(slide_dict)

        outputs = await db.get_outputs(database, post_id)
        result["outputs"] = rows_to_list(outputs)

        brand_dict = row_to_dict(brand)
        if brand_dict:
            accounts = await db.get_accounts(database, post["brand_id"])
            brand_dict["accounts"] = rows_to_list(accounts)
        result["brand"] = brand_dict

        return result
    finally:
        await database.close()


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")

        brand = await db.get_brand(database, post["brand_id"])
        if user["role"] != "admin" and brand and brand["user_id"] != user["id"]:
            raise HTTPException(403, "Access denied")

        slides = await db.get_slides(database, post_id)
        for s in slides:
            await database.execute("DELETE FROM variations WHERE slide_id = ?", (s["id"],))
        await database.execute("DELETE FROM slides WHERE post_id = ?", (post_id,))
        await database.execute("DELETE FROM outputs WHERE post_id = ?", (post_id,))
        await database.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await database.commit()

        if brand:
            upload_dir = Path("uploads") / brand["slug"] / f"post_{post_id}"
            if upload_dir.exists():
                shutil.rmtree(upload_dir, ignore_errors=True)
            output_dir = Path("output") / brand["slug"]
            if output_dir.exists():
                for d in output_dir.rglob(f"post_{post['id']}"):
                    shutil.rmtree(d, ignore_errors=True)

        return {"ok": True}
    finally:
        await database.close()


# --- TikTok Import ---

@app.post("/api/posts/import")
async def import_tiktok_post(data: PostImport, user: dict = Depends(get_current_user)):
    await verify_brand_ownership(data.brand_id, user)
    database = await db.get_db()
    try:
        brand = await db.get_brand(database, data.brand_id)
        if not brand:
            raise HTTPException(404, "Brand not found")

        # Scrape FIRST so we don't create an empty post on failure
        tmp_dir = Path("uploads") / brand["slug"] / f"_import_tmp_{int(datetime.now().timestamp())}"
        download_result = await tiktok_scraper.download_tiktok_slides(
            data.tiktok_url, str(tmp_dir)
        )
        slide_paths = download_result["slides"]
        if not slide_paths:
            raise HTTPException(
                422,
                "Couldn't extract any images from that TikTok URL. "
                "Check the link (must be a photo carousel post) or upload slides manually.",
            )

        today = datetime.now().strftime("%Y-%m-%d")
        cur_num = await database.execute(
            "SELECT COALESCE(MAX(post_number), 0) + 1 AS next_num FROM posts WHERE brand_id = ? AND date = ?",
            (data.brand_id, today),
        )
        next_num = (await cur_num.fetchone())["next_num"]
        post_id = await db.create_post(
            database, data.brand_id,
            today,
            next_num,
            tiktok_url=data.tiktok_url,
            caption=data.caption or "",
        )

        # Move scraped files into the post's final folder
        upload_dir = Path("uploads") / brand["slug"] / f"post_{post_id}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        moved_paths: list[str] = []
        for sp in slide_paths:
            src = Path(sp)
            if not src.exists():
                continue
            dest = upload_dir / src.name
            try:
                src.replace(dest)
            except OSError:
                shutil.copy2(src, dest)
                src.unlink(missing_ok=True)
            moved_paths.append(str(dest))
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
        slide_paths = moved_paths
        if download_result["caption"] and not data.caption:
            await db.update_post(database, post_id, caption=download_result["caption"])
        if download_result["sound_id"]:
            await db.update_post(database, post_id, tiktok_sound_id=download_result["sound_id"])

        # Optional: import TikTok audio as a music track
        music_track_id: Optional[int] = None
        if data.import_audio and download_result.get("music_play_url"):
            try:
                music_play_url = download_result["music_play_url"]
                music_title = download_result.get("music_title") or "TikTok Audio"
                music_author = download_result.get("music_author") or ""

                # Determine track name
                if data.audio_name:
                    track_name = data.audio_name
                elif music_author:
                    track_name = f"{music_author} — {music_title}"
                else:
                    track_name = music_title

                # Download the audio file
                music_dir = upload_dir / "audio"
                music_dir.mkdir(parents=True, exist_ok=True)
                audio_path = music_dir / "tiktok_audio.mp3"

                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=30,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                            "Mobile/15E148 Safari/604.1"
                        ),
                    }
                ) as audio_client:
                    audio_resp = await audio_client.get(music_play_url)
                    if audio_resp.status_code == 200 and len(audio_resp.content) > 1000:
                        audio_path.write_bytes(audio_resp.content)
                        music_track_id = await db.create_music_track(
                            database,
                            name=track_name,
                            file_path=str(audio_path),
                            is_custom=True,
                            user_id=user["id"],
                        )
                        # Link track to all three platforms on this post
                        await db.update_post(
                            database, post_id,
                            youtube_music_track_id=music_track_id,
                            instagram_music_track_id=music_track_id,
                            facebook_music_track_id=music_track_id,
                        )
                        print(f"[import] TikTok audio saved as music track {music_track_id}")
                    else:
                        print(
                            f"[import] TikTok audio download failed "
                            f"(status={audio_resp.status_code}, size={len(audio_resp.content)})"
                        )
            except Exception as audio_err:
                print(f"[import] TikTok audio import failed (continuing): {audio_err}")

        # No auto-OCR — user clicks "Run OCR" manually to save API costs
        accounts = await db.get_accounts(database, data.brand_id)

        for i, slide_path in enumerate(slide_paths):
            slide_type = "hook" if i == 0 else ("cta" if i == len(slide_paths) - 1 else "content")

            slide_id = await db.create_slide(
                database, post_id,
                slide_number=i + 1,
                type=slide_type,
                has_face=False,
                title_text="",
                body_text="",
                cta_text="",
                master_image_path=slide_path,
            )

            for account in accounts:
                await db.create_variation(database, slide_id, account["id"], action="keep")

        return await get_post(post_id, user=user)

    finally:
        await database.close()


@app.post("/api/posts/upload-slides")
async def upload_slides_manually(
    brand_id: int = Form(...),
    caption: str = Form(""),
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    await verify_brand_ownership(brand_id, user)
    database = await db.get_db()
    try:
        brand = await db.get_brand(database, brand_id)
        if not brand:
            raise HTTPException(404, "Brand not found")

        today = datetime.now().strftime("%Y-%m-%d")
        cur_num = await database.execute(
            "SELECT COALESCE(MAX(post_number), 0) + 1 AS next_num FROM posts WHERE brand_id = ? AND date = ?",
            (brand_id, today),
        )
        next_num = (await cur_num.fetchone())["next_num"]
        post_id = await db.create_post(
            database, brand_id,
            today,
            next_num,
            caption=caption,
        )

        upload_dir = Path("uploads") / brand["slug"] / f"post_{post_id}"
        upload_dir.mkdir(parents=True, exist_ok=True)

        slide_paths = []
        for i, f in enumerate(files):
            ext = Path(f.filename or "image.jpg").suffix or ".jpg"
            path = upload_dir / f"slide_{i + 1:02d}{ext}"
            content = await f.read()
            path.write_bytes(content)
            slide_paths.append(str(path))

        # No auto-OCR — user clicks "Run OCR" manually to save API costs
        accounts = await db.get_accounts(database, brand_id)

        for i, slide_path in enumerate(slide_paths):
            slide_type = "hook" if i == 0 else ("cta" if i == len(slide_paths) - 1 else "content")

            slide_id = await db.create_slide(
                database, post_id,
                slide_number=i + 1,
                type=slide_type,
                has_face=False,
                title_text="",
                body_text="",
                cta_text="",
                master_image_path=slide_path,
            )

            for account in accounts:
                await db.create_variation(database, slide_id, account["id"], action="keep")

        return await get_post(post_id, user=user)

    finally:
        await database.close()


# =============================================
# SLIDE ROUTES
# =============================================

@app.put("/api/posts/{post_id}/slides/{slide_number}")
async def update_slide(post_id: int, slide_number: int, data: SlideUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        cursor = await database.execute(
            "SELECT id FROM slides WHERE post_id = ? AND slide_number = ?",
            (post_id, slide_number)
        )
        slide = await cursor.fetchone()
        if not slide:
            raise HTTPException(404, "Slide not found")

        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if updates:
            await db.update_slide(database, slide["id"], **updates)

        cursor = await database.execute("SELECT * FROM slides WHERE id = ?", (slide["id"],))
        return row_to_dict(await cursor.fetchone())
    finally:
        await database.close()

@app.post("/api/posts/{post_id}/slides/{slide_number}/image")
async def upload_slide_image(post_id: int, slide_number: int, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            "SELECT s.id, p.brand_id FROM slides s JOIN posts p ON s.post_id = p.id WHERE s.post_id = ? AND s.slide_number = ?",
            (post_id, slide_number)
        )
        slide = await cursor.fetchone()
        if not slide:
            raise HTTPException(404, "Slide not found")

        await verify_brand_ownership(slide["brand_id"], user)

        brand = await db.get_brand(database, slide["brand_id"])
        save_dir = Path("uploads") / brand["slug"] / f"post_{post_id}"
        save_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(file.filename).suffix or ".png"
        save_path = save_dir / f"master_slide_{slide_number}{ext}"
        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        await db.update_slide(database, slide["id"], master_image_path=str(save_path))
        return {"path": str(save_path)}
    finally:
        await database.close()


@app.post("/api/posts/{post_id}/rerun-ocr")
async def rerun_ocr(post_id: int, user: dict = Depends(get_current_user)):
    """Re-run OCR on all slides of a post using updated extraction logic."""
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        slides = await db.get_slides(database, post_id)
        if not slides:
            raise HTTPException(400, "No slides found")

        slide_paths = [s["master_image_path"] for s in slides if s["master_image_path"]]
        if not slide_paths:
            raise HTTPException(400, "No slide images found")

        # Fetch the Anthropic key from the Postgres settings table, falling back
        # to the env var. Surface a clear 400 if nothing is configured so the
        # frontend toast tells the user to set it in Settings.
        _u_rows = await db.get_user_settings(database, user["id"])
        api_key = (_u_rows.get("anthropic_api_key")
                   or await db.get_setting(database, "anthropic_api_key")
                   or await db.get_setting(database, "claude_api_key"))
        if not api_key:
            import os as _os
            api_key = _os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(400, "Anthropic API key not configured — add one in Settings")

        try:
            ocr_results = ocr.extract_slide_texts(slide_paths, api_key=api_key)
        except ocr.OCRError as e:
            raise HTTPException(502, f"OCR failed: {e}")

        updated = []
        extracted_any = False
        for i, slide in enumerate(slides):
            if i < len(ocr_results):
                ocr_data = ocr_results[i]
                if ocr_data.get("title_text") or ocr_data.get("body_text") or ocr_data.get("cta_text"):
                    extracted_any = True
                await db.update_slide(database, slide["id"],
                    type=ocr_data.get("type", slide["type"]),
                    title_text=ocr_data.get("title_text", ""),
                    body_text=ocr_data.get("body_text", ""),
                    cta_text=ocr_data.get("cta_text", ""),
                )
                updated.append({"slide_number": slide["slide_number"], **ocr_data})

        return {"updated": len(updated), "extracted_any": extracted_any, "slides": updated}
    finally:
        await database.close()


@app.get("/api/posts/{post_id}/output-slides")
async def list_output_slides(post_id: int, user: dict = Depends(get_current_user)):
    """List all generated slide images for each account."""
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        outputs = await db.get_outputs(database, post_id)
        accounts = await db.get_accounts(database, post["brand_id"])
        account_map = {a["id"]: dict(a) for a in accounts}

        result = []
        for out in outputs:
            slides_dir = out["slides_dir"]
            slides_3x4 = []
            slides_9x16 = []
            if slides_dir and Path(slides_dir).exists():
                for f in sorted(Path(slides_dir).iterdir()):
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        if "_9x16" in f.stem:
                            slides_9x16.append(str(f))
                        else:
                            slides_3x4.append(str(f))

            acc = account_map.get(out["account_id"], {})
            result.append({
                "account_id": out["account_id"],
                "account_name": acc.get("name", f"Account {out['account_id']}"),
                "account_role": acc.get("role", ""),
                "slides_3x4": slides_3x4,
                "slides_9x16": slides_9x16,
                "video_path": out["video_path"],
                "posting_status": out["posting_status"],
            })
        return result
    finally:
        await database.close()


@app.post("/api/posts/{post_id}/regenerate-slide")
async def regenerate_single_slide(post_id: int, data: RegenerateSlide, user: dict = Depends(get_current_user)):
    """Regenerate overlay for a single slide of a specific account.
    Allows adjusting text content and positioning (font sizes, y_ratios)."""
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        brand = await db.get_brand(database, post["brand_id"])
        slides = await db.get_slides(database, post_id)
        slide = next((s for s in slides if s["slide_number"] == data.slide_number), None)
        if not slide:
            raise HTTPException(404, f"Slide {data.slide_number} not found")

        # Use provided text or fall back to stored slide text
        title_text = data.title_text if data.title_text is not None else slide["title_text"]
        body_text = data.body_text if data.body_text is not None else slide["body_text"]
        cta_text = data.cta_text if data.cta_text is not None else slide["cta_text"]

        # Update slide text in DB if changed
        text_updates = {}
        if data.title_text is not None:
            text_updates["title_text"] = data.title_text
        if data.body_text is not None:
            text_updates["body_text"] = data.body_text
        if data.cta_text is not None:
            text_updates["cta_text"] = data.cta_text
        if text_updates:
            await db.update_slide(database, slide["id"], **text_updates)

        # Determine source image (master or variation replacement)
        variations = await db.get_variations(database, post_id=post_id, account_id=data.account_id)
        var = next((v for v in variations if v["slide_id"] == slide["id"]), None)
        if var and var["action"] in ("replace", "generate") and var["replacement_image_path"]:
            source_image = var["replacement_image_path"]
        else:
            source_image = slide["master_image_path"]

        if not source_image or not Path(source_image).exists():
            raise HTTPException(400, "Source image not found")

        # Find account and output dir
        account = await database.execute("SELECT * FROM accounts WHERE id = ?", (data.account_id,))
        account = await account.fetchone()
        if not account:
            raise HTTPException(404, "Account not found")

        out_dir = Path("output") / brand["slug"] / post["date"] / account["name"] / f"post_{post['id']}"
        slides_dir = out_dir / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        output_path = str(slides_dir / f"slide_{data.slide_number:02d}.png")
        bg_color = "#000000"  # Always black for 9:16 canvas bars

        # Build custom text blocks with overridden positioning
        slide_type = slide["type"]
        custom_texts = []

        if slide_type == "hook":
            text = title_text or body_text or ""
            if text:
                custom_texts.append({
                    "text": text,
                    "font_size": data.font_size_title or 56,
                    "y_ratio": data.y_ratio_title or 0.30,
                    "x_ratio": data.x_ratio_title if data.x_ratio_title is not None else 0.5,
                    "scale": data.scale_title if data.scale_title is not None else 1.0,
                })
        elif slide_type == "content":
            if title_text:
                custom_texts.append({
                    "text": title_text,
                    "font_size": data.font_size_title or 52,
                    "y_ratio": data.y_ratio_title or 0.28,
                    "x_ratio": data.x_ratio_title if data.x_ratio_title is not None else 0.5,
                    "scale": data.scale_title if data.scale_title is not None else 1.0,
                })
            if body_text:
                custom_texts.append({
                    "text": body_text,
                    "font_size": data.font_size_body or 38,
                    "y_ratio": data.y_ratio_body or 0.48,
                    "x_ratio": data.x_ratio_body if data.x_ratio_body is not None else 0.5,
                    "scale": data.scale_body if data.scale_body is not None else 1.0,
                })
        elif slide_type == "cta":
            if title_text:
                custom_texts.append({
                    "text": title_text,
                    "font_size": data.font_size_title or 48,
                    "y_ratio": data.y_ratio_title or 0.25,
                    "x_ratio": data.x_ratio_title if data.x_ratio_title is not None else 0.5,
                    "scale": data.scale_title if data.scale_title is not None else 1.0,
                })
            if body_text:
                custom_texts.append({
                    "text": body_text,
                    "font_size": data.font_size_body or 34,
                    "y_ratio": data.y_ratio_body or 0.45,
                    "x_ratio": data.x_ratio_body if data.x_ratio_body is not None else 0.5,
                    "scale": data.scale_body if data.scale_body is not None else 1.0,
                })
            if cta_text:
                custom_texts.append({
                    "text": cta_text,
                    "font_size": data.font_size_cta or 42,
                    "y_ratio": data.y_ratio_cta or 0.75,
                    "x_ratio": data.x_ratio_cta if data.x_ratio_cta is not None else 0.5,
                    "scale": data.scale_cta if data.scale_cta is not None else 1.0,
                })

        # Use overlay engine directly with custom text blocks.
        # Pillow is CPU-bound — run in a thread so the event loop stays free
        # to handle other requests while this slide renders.
        from PIL import Image
        font_weight = data.font_weight or overlay.DEFAULT_WEIGHT
        text_style = data.text_style or "stroke"

        _source = source_image
        _output_path = output_path
        _bg = bg_color
        _custom_texts = custom_texts
        _font_weight = font_weight
        _text_style = text_style

        def _render_slide():
            _img = Image.open(_source).convert("RGB")
            _img_3x4 = overlay.resize_to_3x4(_img)
            if _custom_texts:
                _img_3x4 = overlay._apply_text_block(
                    _img_3x4, _custom_texts,
                    weight=_font_weight, text_style=_text_style,
                )
            _out_3x4 = Path(_output_path)
            _out_3x4.parent.mkdir(parents=True, exist_ok=True)
            _img_3x4.save(str(_out_3x4), "PNG")
            _img_9x16 = overlay.convert_3x4_to_9x16(_img_3x4, _bg)
            _out_9x16 = _out_3x4.parent / f"{_out_3x4.stem}_9x16{_out_3x4.suffix}"
            _img_9x16.save(str(_out_9x16), "PNG")
            return str(_out_3x4), str(_out_9x16)

        slide_3x4_path, slide_9x16_path = await asyncio.to_thread(_render_slide)

        return {
            "slide_3x4": slide_3x4_path,
            "slide_9x16": slide_9x16_path,
            "slide_number": data.slide_number,
            "account_id": data.account_id,
        }
    finally:
        await database.close()


class RegenerateVideo(BaseModel):
    account_id: int
    platform: Optional[str] = None  # "youtube" | "instagram" | "facebook"; None = legacy shared video


async def _music_path_for(database, post: dict, platform: Optional[str]) -> Optional[str]:
    """Resolve the music file path for a post/platform, falling back to legacy.

    Order:
      1. The exact platform's track (if `platform` is set)
      2. The legacy `music_track_id`
      3. Any other per-platform track that's set (so the legacy regenerate
         picks up audio when only the per-platform slots have been filled)
    """
    candidates = []
    if platform:
        candidates.append(post.get(f"{platform}_music_track_id"))
    candidates.append(post.get("music_track_id"))
    for plat in ("youtube", "instagram", "facebook"):
        if platform != plat:
            candidates.append(post.get(f"{plat}_music_track_id"))
    for tid in candidates:
        if not tid:
            continue
        c = await database.execute("SELECT file_path FROM music_tracks WHERE id = ?", (tid,))
        t = await c.fetchone()
        if t and t["file_path"]:
            return t["file_path"]
    return None


@app.post("/api/posts/{post_id}/regenerate-video")
async def regenerate_single_video(post_id: int, data: RegenerateVideo, user: dict = Depends(get_current_user)):
    """Rebuild the video for a specific account.

    If `platform` is set (youtube|instagram|facebook), render with that
    platform's profile (duration cap + its music pick) and store under
    `outputs.{platform}_video_path`. Otherwise render the legacy shared
    video and store under `outputs.video_path`.
    """
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        brand = await db.get_brand(database, post["brand_id"])
        cursor = await database.execute("SELECT * FROM accounts WHERE id = ?", (data.account_id,))
        account = await cursor.fetchone()
        if not account:
            raise HTTPException(404, "Account not found")

        music_path = await _music_path_for(database, dict(post), data.platform)

        # Stitch from the per-account slide cache as it sits on disk RIGHT
        # NOW. The cache is what the user sees in the Preview & Downloads
        # panel — it reflects every slide-level edit they've made via the
        # slide editor (text, font, position, style). Re-rendering from
        # master here would silently destroy those edits, since slide
        # overlay params are not persisted to the DB. If the user wants the
        # latest master image to flow into the video, they regenerate the
        # individual slide first, then regenerate the video.
        slides_for_post = await db.get_slides(database, post_id)
        if not slides_for_post:
            raise HTTPException(400, "No slides on this post — generate it first")

        out_dir = (
            Path("output")
            / brand["slug"]
            / post["date"]
            / account["name"]
            / f"post_{post['id']}"
        )
        slides_dir = out_dir / "slides"

        slide_paths = []
        for slide in slides_for_post:
            cache_9x16 = slides_dir / f"slide_{slide['slide_number']:02d}_9x16.png"
            if cache_9x16.exists():
                slide_paths.append(str(cache_9x16))

        if len(slide_paths) < 2:
            # Cache is missing or stale — fall back to a full re-render so
            # the user isn't blocked. This path runs when a post hasn't been
            # generated yet for this account, or the output dir was wiped.
            from services.generator import render_account_slides
            slides_dir, slide_paths = await render_account_slides(
                database, dict(post), dict(brand), dict(account), slides_for_post,
            )
            out_dir = slides_dir.parent

        if len(slide_paths) < 2:
            raise HTTPException(400, f"Need at least 2 slides to build a video (found {len(slide_paths)})")

        filename = f"video_{data.platform}.mp4" if data.platform else "video.mp4"
        video_path = str(out_dir / filename)

        if data.platform:
            await video.build_platform_video(
                slide_paths=slide_paths,
                output_path=video_path,
                platform=data.platform,
                music_path=music_path,
            )
        else:
            await video.build_video(
                slide_paths=slide_paths,
                output_path=video_path,
                music_path=music_path,
            )

        # Update output record — platform-specific column when platform set,
        # else the legacy shared column.
        c = await database.execute(
            "SELECT id FROM outputs WHERE post_id = ? AND account_id = ?", (post_id, data.account_id)
        )
        existing = await c.fetchone()
        if existing:
            col = f"{data.platform}_video_path" if data.platform else "video_path"
            await db.update_output(database, existing["id"], **{col: video_path})

        return {
            "video_path": video_path,
            "platform": data.platform,
            "account_id": data.account_id,
            "slide_count": len(slide_paths),
        }
    finally:
        await database.close()


@app.put("/api/posts/{post_id}/music")
async def update_post_music(post_id: int, data: PostMusic, user: dict = Depends(get_current_user)):
    """Set per-platform music track ids on a post (None to unset a platform)."""
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        updates: dict = {}
        for plat in ("youtube", "instagram", "facebook"):
            col = f"{plat}_music_track_id"
            val = getattr(data, col)
            # Interpret 0 as clear; anything else (incl None-left-unchanged) handled below
            updates[col] = val if val else None

        await db.update_post(database, post_id, **updates)
        return {"ok": True, **updates}
    finally:
        await database.close()


# =============================================
# VARIATION ROUTES
# =============================================

@app.put("/api/variations/{variation_id}/action")
async def update_variation(variation_id: int, data: VariationUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """SELECT v.id, p.brand_id FROM variations v
               JOIN slides s ON v.slide_id = s.id
               JOIN posts p ON s.post_id = p.id
               WHERE v.id = ?""", (variation_id,)
        )
        var = await cursor.fetchone()
        if not var:
            raise HTTPException(404, "Variation not found")
        await verify_brand_ownership(var["brand_id"], user)

        await db.update_variation(database, variation_id, action=data.action)
        cursor = await database.execute("SELECT * FROM variations WHERE id = ?", (variation_id,))
        return row_to_dict(await cursor.fetchone())
    finally:
        await database.close()

@app.post("/api/variations/{variation_id}/upload")
async def upload_variation_image(variation_id: int, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """SELECT v.id, v.slide_id, v.account_id, s.post_id, s.slide_number, a.name as account_name, p.brand_id
               FROM variations v
               JOIN slides s ON v.slide_id = s.id
               JOIN accounts a ON v.account_id = a.id
               JOIN posts p ON s.post_id = p.id
               WHERE v.id = ?""", (variation_id,)
        )
        var = await cursor.fetchone()
        if not var:
            raise HTTPException(404, "Variation not found")

        await verify_brand_ownership(var["brand_id"], user)

        brand = await db.get_brand(database, var["brand_id"])
        save_dir = Path("uploads") / brand["slug"] / f"post_{var['post_id']}" / "variations"
        save_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(file.filename).suffix or ".png"
        save_path = save_dir / f"slide_{var['slide_number']}_{var['account_name']}{ext}"
        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        await db.update_variation(
            database, variation_id,
            action="replace",
            replacement_image_path=str(save_path),
            status="approved"
        )
        return {"path": str(save_path)}
    finally:
        await database.close()

@app.post("/api/variations/{variation_id}/generate")
async def generate_variation_image(variation_id: int, data: FluxGenerate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """SELECT v.*, s.post_id, s.slide_number, a.name as account_name, p.brand_id
               FROM variations v
               JOIN slides s ON v.slide_id = s.id
               JOIN accounts a ON v.account_id = a.id
               JOIN posts p ON s.post_id = p.id
               WHERE v.id = ?""", (variation_id,)
        )
        var = await cursor.fetchone()
        if not var:
            raise HTTPException(404, "Variation not found")

        await verify_brand_ownership(var["brand_id"], user)

        brand = await db.get_brand(database, var["brand_id"])
        save_dir = Path("uploads") / brand["slug"] / f"post_{var['post_id']}" / "generated"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"slide_{var['slide_number']}_{var['account_name']}.png"

        _u_rows2 = await db.get_user_settings(database, user["id"])
        api_key = _u_rows2.get("openai_api_key") or await db.get_setting(database, "openai_api_key")

        # Resolve reference image: prefer previously-generated image (for edits),
        # fall back to original slide master image (for first-time generation).
        ref_path: str | None = None
        if data.use_reference:
            if var.get("replacement_image_path") and Path(var["replacement_image_path"]).exists():
                ref_path = var["replacement_image_path"]
            else:
                cursor2 = await database.execute(
                    "SELECT master_image_path FROM slides WHERE id = ?", (var["slide_id"],)
                )
                slide_row = await cursor2.fetchone()
                if slide_row and slide_row["master_image_path"]:
                    ref_path = slide_row["master_image_path"]

        await openai_image.generate_image(
            prompt=data.prompt,
            output_path=str(save_path),
            reference_image_path=ref_path,
            api_key=api_key,
        )

        await db.update_variation(
            database, variation_id,
            action="generate",
            replacement_image_path=str(save_path),
            generated_prompt=data.prompt,
            status="generated"
        )

        return {"path": str(save_path), "prompt": data.prompt}
    finally:
        await database.close()

@app.post("/api/variations/{variation_id}/approve")
async def approve_variation(variation_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute(
            """SELECT v.id, p.brand_id FROM variations v
               JOIN slides s ON v.slide_id = s.id
               JOIN posts p ON s.post_id = p.id
               WHERE v.id = ?""", (variation_id,)
        )
        var = await cursor.fetchone()
        if not var:
            raise HTTPException(404, "Variation not found")
        await verify_brand_ownership(var["brand_id"], user)

        await db.update_variation(database, variation_id, status="approved")
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# GENERATION
# =============================================

generation_status = {}

@app.post("/api/posts/{post_id}/generate")
async def generate_post_content(post_id: int, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)
    finally:
        await database.close()

    generation_status[post_id] = {"status": "generating", "progress": 0}

    async def run_generation():
        database = await db.get_db()
        try:
            result = await generator.generate_post(post_id, database)
            generation_status[post_id] = {"status": "done", "result": result}
        except Exception as e:
            generation_status[post_id] = {"status": "error", "error": str(e)}
        finally:
            await database.close()

    background_tasks.add_task(run_generation)
    return {"status": "generating", "post_id": post_id}

@app.get("/api/posts/{post_id}/generate/status")
async def get_generation_status(post_id: int, user: dict = Depends(get_current_user)):
    return generation_status.get(post_id, {"status": "idle"})


@app.post("/api/posts/{post_id}/post-now")
async def post_now(post_id: int, user: dict = Depends(get_current_user)):
    """Push each account's generated video to every connected platform on that account.

    Uses the same adapters as the Clipping dispatcher. An account is skipped for a
    platform if it has no `{platform}_token`. Local video files are exposed via the
    `/files/output/...` static mount using `oauth_redirect_base` as the public host.
    Returns per-account / per-platform results.
    """
    from services.posting import tiktok as _tt, youtube as _yt, instagram as _ig, facebook as _fb, PostingError

    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        cfg = await db.get_site_config(database)
        public_base = (cfg.get("oauth_redirect_base") or "").rstrip("/")
        if not public_base:
            raise HTTPException(400, "oauth_redirect_base not configured in /settings — needed to expose videos to platforms")

        outputs = await db.get_outputs(database, post_id)
        if not outputs:
            raise HTTPException(400, "No generated outputs — generate the post first")

        caption = post.get("caption") or ""
        results: list[dict] = []
        any_success = False

        for out in outputs:
            account = await db.get_account(database, out["account_id"])
            if not account:
                continue

            legacy_video_path = out.get("video_path")
            if not legacy_video_path and not any(
                out.get(f"{p}_video_path") for p in ("youtube", "instagram", "facebook")
            ):
                results.append({
                    "account_id": out["account_id"],
                    "account_name": account.get("name"),
                    "skipped": "no video generated yet",
                })
                continue

            # Build a public URL the platforms can pull. In prod, Apache only
            # proxies /api/* to the backend — the /files mount isn't reachable
            # externally — so we use the existing /api/files/{path} route.
            from urllib.parse import quote
            # Cache-bust token shared across all platform URLs for this
            # post_now invocation. Different invocation → different token,
            # so retry attempts don't share URLs with prior attempts.
            _video_t = secrets.token_urlsafe(6)
            def _public_video_url(p: Optional[str]) -> Optional[str]:
                path = (out.get(f"{p}_video_path") if p else None) or legacy_video_path
                if not path:
                    return None
                rel = path.lstrip("./")
                enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
                # ?for={account_id} triggers per-account container-metadata
                # remux; ?t=... breaks URL clustering across accounts.
                return f"{public_base}/api/files/{enc}?for={account['id']}&t={_video_t}"

            # Refresh expiring tokens (YouTube/TikTok access tokens are short-lived).
            async def _fresh_token(platform_name: str) -> Optional[str]:
                token_local = account.get(f"{platform_name}_token")
                if not token_local:
                    return None
                exp = account.get(f"{platform_name}_expires_at")
                refresh = account.get(f"{platform_name}_refresh_token")
                needs_refresh = False
                if exp:
                    try:
                        exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
                        # refresh if <2 min of life left
                        if exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=2):
                            needs_refresh = True
                    except Exception:
                        pass
                if not needs_refresh or not refresh:
                    return token_local
                # Heuristic for which app owns this token:
                #   - facebook_* is always Meta (FB Login).
                #   - instagram_* is Meta if a sibling facebook_token exists
                #     (came from FB Login fan-out); otherwise it's the
                #     standalone Instagram Login app.
                if platform_name == "facebook":
                    provider = "meta"
                elif platform_name == "instagram":
                    provider = "meta" if account.get("facebook_token") else "instagram"
                else:
                    provider = platform_name
                cid = cfg.get(f"oauth_{provider}_client_id", "")
                csec = cfg.get(f"oauth_{provider}_client_secret", "")
                if not cid or not csec:
                    return token_local
                try:
                    # Route the OAuth refresh through the account's
                    # residential proxy (when set) so the refresh's origin
                    # IP matches every other call this account makes.
                    refreshed = await oauth_svc.refresh_access_token(
                        provider, refresh, cid, csec,
                        proxy_url=account.get("proxy_url") or None,
                    )
                except Exception:
                    return token_local
                new_token = refreshed.get("access_token")
                if not new_token:
                    return token_local
                updates_tok: dict = {f"{platform_name}_token": new_token}
                if refreshed.get("refresh_token"):
                    updates_tok[f"{platform_name}_refresh_token"] = refreshed["refresh_token"]
                if refreshed.get("expires_in"):
                    new_exp = datetime.now(timezone.utc) + timedelta(seconds=int(refreshed["expires_in"]))
                    updates_tok[f"{platform_name}_expires_at"] = new_exp.isoformat()
                try:
                    await db.update_account(database, account["id"], **updates_tok)
                except Exception:
                    pass
                return new_token

            targets = [
                ("tiktok",    _tt, await _fresh_token("tiktok")),
                ("youtube",   _yt, await _fresh_token("youtube")),
                ("instagram", _ig, await _fresh_token("instagram")),
                ("facebook",  _fb, await _fresh_token("facebook")),
            ]
            # Build public URLs for the 3:4 slides (used for TikTok slideshow).
            # Route through /api/files-jpg/ — TikTok's photo API rejects PNG with
            # file_format_check_failed, so we re-encode to JPEG on serve.
            # `?for={account_id}` triggers per-account JPEG params + synthetic
            # EXIF; `?t=...` is a cache-bust token so TikTok's spam clustering
            # can't dedupe the URL across different posts/accounts.
            slide_urls: list[str] = []
            slides_dir = out.get("slides_dir")
            if slides_dir and Path(slides_dir).exists():
                from urllib.parse import quote as _q
                _t = secrets.token_urlsafe(6)
                for f in sorted(Path(slides_dir).iterdir()):
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and "_9x16" not in f.stem:
                        rel = str(f).lstrip("./")
                        enc = "/".join(_q(seg, safe="") for seg in rel.split("/") if seg)
                        slide_urls.append(
                            f"{public_base}/api/files-jpg/{enc}?for={account['id']}&t={_t}"
                        )

            # TikTok per-(post, variation) settings live on the outputs row.
            # User picks them on the Generate tab; dispatcher reads them
            # here. No site_config fallback — TikTok forbids any global
            # default value for privacy.
            def _tiktok_kwargs_for_output(out_row: dict) -> tuple[dict, Optional[str]]:
                """Returns (kwargs, error). When error is set, dispatcher
                should mark the platform failed with that message and skip
                the API call."""
                if out_row.get("tiktok_post_as_draft"):
                    # Inbox / draft mode: TikTok ignores every post_info
                    # field. The user composes the rest inside the TikTok
                    # app once the draft lands. Must use "INBOX" — the
                    # adapter only recognises INBOX as the draft path.
                    return {"post_mode": "INBOX"}, None
                privacy = out_row.get("tiktok_privacy_level")
                if not privacy:
                    return {}, (
                        "TikTok privacy not set for this variation. Open "
                        "the Generate tab → expand TikTok settings → pick "
                        "a privacy level (or enable Post as draft)."
                    )
                kwargs: dict = {
                    "post_mode": "DIRECT_POST",
                    "privacy_level": privacy.upper(),
                    "disable_comment": not bool(out_row.get("tiktok_allow_comment")),
                    "disable_duet":    not bool(out_row.get("tiktok_allow_duet")),
                    "disable_stitch":  not bool(out_row.get("tiktok_allow_stitch")),
                    "brand_content_toggle": bool(out_row.get("tiktok_disclose_branded_content")),
                    "brand_organic_toggle": bool(out_row.get("tiktok_disclose_your_brand")),
                }
                if kwargs["brand_content_toggle"] and not out_row.get("tiktok_consent_at"):
                    return {}, (
                        "Branded Content selected without saving the music "
                        "usage acknowledgement. Re-open TikTok settings on "
                        "the Generate tab and Save."
                    )
                return kwargs, None

            # Per-account residential proxy: when set, every adapter call
            # AND the OAuth refresh above route through this URL so TikTok
            # / YT / IG / FB see a stable residential origin for this
            # account (especially important for US-targeted accounts on
            # platforms that deprioritise datacenter IPs).
            account_proxy = account.get("proxy_url") or None

            per_platform: dict = {}
            for name, adapter, token in targets:
                if not token:
                    per_platform[name] = {"status": "skipped", "reason": "not connected"}
                    continue
                try:
                    if name == "tiktok":
                        tt_kwargs, tt_err = _tiktok_kwargs_for_output(out)
                        if tt_err:
                            per_platform[name] = {"status": "failed", "error": tt_err}
                            continue
                        if slide_urls:
                            # Swipeable photo slideshow. Duet/Stitch don't
                            # apply to photo posts — strip those kwargs.
                            slideshow_kwargs = {
                                k: v for k, v in tt_kwargs.items()
                                if k not in ("disable_duet", "disable_stitch")
                            }
                            res = await _tt.upload_photo_slideshow(
                                token, slide_urls, caption,
                                proxy_url=account_proxy,
                                **slideshow_kwargs,
                            )
                        else:
                            plat_url = _public_video_url(None)
                            if not plat_url:
                                per_platform[name] = {"status": "skipped", "reason": "no video rendered for this platform"}
                                continue
                            res = await adapter.upload_video(
                                token, plat_url, caption,
                                proxy_url=account_proxy,
                                **tt_kwargs,
                            )
                    else:
                        plat_url = _public_video_url(name if name in ("youtube", "instagram", "facebook") else None)
                        if not plat_url:
                            per_platform[name] = {"status": "skipped", "reason": "no video rendered for this platform"}
                            continue
                        # Per-platform required IDs from the Account row.
                        # Facebook needs the Page id (`page_id`); Instagram
                        # needs the IG Business Account id (`ig_user_id`).
                        # The Clipping dispatcher already does this from
                        # artist_accounts; the Brand path was missing it
                        # and the FB adapter raised "Facebook requires
                        # page_id". The OAuth callback persists these into
                        # `accounts.{platform}_user_id` for both Meta-flow
                        # connections and standalone IG.
                        plat_kwargs: dict = {}
                        if name == "facebook" and account.get("facebook_user_id"):
                            plat_kwargs["page_id"] = account["facebook_user_id"]
                        if name == "instagram" and account.get("instagram_user_id"):
                            plat_kwargs["ig_user_id"] = account["instagram_user_id"]
                        res = await adapter.upload_video(
                            token, plat_url, caption,
                            proxy_url=account_proxy,
                            **plat_kwargs,
                        )
                    per_platform[name] = {
                        "status": "posted",
                        "platform_post_id": res.get("platform_post_id"),
                        "permalink": res.get("permalink"),
                        **({"draft": True} if res.get("draft") else {}),
                    }
                    any_success = True
                    # flag on outputs table; mark drafts so the dashboard
                    # can render a "draft" pill and the view poller skips.
                    # Also clear any prior error so FailedOutputsSection
                    # removes this platform from its list.
                    try:
                        update_kwargs = {f"{name}_posted": True, f"{name}_error": None}
                        if res.get("draft"):
                            update_kwargs["posted_as_draft"] = True
                        await db.update_output(database, out["id"], **update_kwargs)
                    except Exception:
                        pass
                except PostingError as e:
                    err_msg = str(e)[:300]
                    # Auto-fallback to INBOX when TikTok rejects DIRECT_POST for unaudited apps
                    if name == "tiktok" and "unaudited_client_can_only_post_to_private_accounts" in err_msg.lower():
                        try:
                            if slide_urls:
                                res = await _tt.upload_photo_slideshow(
                                    token, slide_urls, caption,
                                    proxy_url=account_proxy, post_mode="INBOX",
                                )
                            else:
                                _pu = _public_video_url(None)
                                if not _pu:
                                    raise RuntimeError("no_video")
                                res = await _tt.upload_video(
                                    token, _pu, caption,
                                    proxy_url=account_proxy, post_mode="INBOX",
                                )
                            per_platform[name] = {
                                "status": "posted", "draft": True,
                                "platform_post_id": res.get("platform_post_id"),
                            }
                            any_success = True
                            try:
                                await db.update_output(database, out["id"], **{
                                    f"{name}_posted": True, f"{name}_error": None,
                                    "posted_as_draft": True,
                                })
                            except Exception:
                                pass
                            continue
                        except Exception:
                            pass  # fall through to record original error
                    per_platform[name] = {"status": "failed", "error": err_msg, "friendly_error": _friendly_error(err_msg)}
                    try:
                        await db.update_output(database, out["id"], **{f"{name}_error": err_msg})
                        print(f"[post_now] stored {name}_error on output {out['id']}: {err_msg[:80]}")
                    except Exception as _se:
                        print(f"[post_now] FAILED to store {name}_error on output {out['id']}: {_se}")
                except Exception as e:
                    err_msg = f"{type(e).__name__}: {str(e)[:250]}"
                    per_platform[name] = {"status": "failed", "error": err_msg, "friendly_error": _friendly_error(err_msg)}
                    try:
                        await db.update_output(database, out["id"], **{f"{name}_error": err_msg})
                        print(f"[post_now] stored {name}_error on output {out['id']}: {err_msg[:80]}")
                    except Exception as _se:
                        print(f"[post_now] FAILED to store {name}_error on output {out['id']}: {_se}")

            results.append({
                "output_id": out["id"],
                "account_id": out["account_id"],
                "account_name": account.get("name"),
                "platforms": per_platform,
            })

        if any_success:
            try:
                await db.update_post(database, post_id, status="posted")
            except Exception:
                pass
            # Send HURRAY result email to the post owner
            try:
                from services.email import send_post_result_email as _send_result
                # Flatten per-account / per-platform results into a simple list
                flat_results: list[dict] = []
                for r in results:
                    for plat, pd in r.get("platforms", {}).items():
                        if pd.get("status") == "skipped":
                            continue  # don't include not-connected platforms in email
                        flat_results.append({
                            "platform": plat,
                            "variation_name": r.get("account_name") or plat,
                            "status": pd.get("status", "failed"),
                            "error": pd.get("error"),
                        })
                brand = await db.get_brand(database, post["brand_id"])
                brand_name = (brand or {}).get("name") or "Brand"
                cfg_e = await db.get_site_config(database)
                dash_url = (cfg_e.get("oauth_redirect_base") or "https://icreateflow.com").rstrip("/") + "/dashboard"
                asyncio.create_task(_send_result(
                    user["email"],
                    brand_name,
                    flat_results,
                    dashboard_url=dash_url,
                ))
            except Exception:
                pass  # Never block the response

        return {"ok": any_success, "results": results}
    finally:
        await database.close()


@app.get("/api/posts/{post_id}/failed-outputs")
async def get_failed_outputs(post_id: int, user: dict = Depends(get_current_user)):
    """Return outputs that have at least one platform posting error.

    Used by FailedOutputsSection on the Generate tab to show persistent
    per-platform failures for both manual Post Now and scheduled dispatch.
    """
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        outputs = await db.get_outputs(database, post_id)
        result = []
        for out in outputs:
            out = dict(out)
            platforms: dict = {}
            for plat in ("tiktok", "youtube", "instagram", "facebook"):
                err = out.get(f"{plat}_error")
                # Show error regardless of whether the platform previously posted
                # (a new post-now attempt can fail even if an earlier one succeeded)
                if err:
                    platforms[plat] = {
                        "error": err,
                        "friendly_error": _friendly_error(err),
                        "draft": False,
                    }
            if not platforms:
                continue
            account = await db.get_account(database, out["account_id"])
            result.append({
                "output_id": out["id"],
                "account_id": out["account_id"],
                "account_name": dict(account).get("name") if account else f"Account {out['account_id']}",
                "platforms": platforms,
            })
        return result
    finally:
        await database.close()


@app.post("/api/outputs/{output_id}/retry")
async def retry_output(
    output_id: int,
    mode: str = Query("normal", description="normal | draft | delayed"),
    user: dict = Depends(get_current_user),
):
    """Retry failed platforms for a brand post output.

    mode=normal  — immediately re-attempt all platforms where an error is stored
                   and the platform hasn't successfully posted yet.
    mode=draft   — TikTok only, posts immediately using INBOX mode (user publishes
                   from the TikTok app). Clears tiktok_error on success.
    mode=delayed — TikTok only, stores tiktok_retry_after = NOW() + 6 hours so the
                   brand scheduler re-attempts TikTok without re-scheduling the
                   whole post. Clears tiktok_error immediately (will be re-set if
                   the delayed attempt also fails).
    """
    from services.posting import tiktok as _tt, youtube as _yt, instagram as _ig, facebook as _fb
    from services.posting import PostingError
    from urllib.parse import quote

    database = await db.get_db()
    try:
        # Ownership check: output → post → brand → user
        cur = await database.execute(
            """
            SELECT o.*, p.caption, p.brand_id, p.status AS post_status
            FROM outputs o
            JOIN posts p ON p.id = o.post_id
            WHERE o.id = ?
            """,
            (output_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Output not found")
        out = dict(row)
        await verify_brand_ownership(out["brand_id"], user)

        # Check there's something to retry (error stored)
        has_error = any(out.get(f"{p}_error") for p in ("tiktok", "youtube", "instagram", "facebook"))
        if not has_error:
            raise HTTPException(400, "No failed platforms on this output")

        account = await db.get_account(database, out["account_id"])
        if not account:
            raise HTTPException(404, "Account not found")
        account = dict(account)

        cfg = await db.get_site_config(database)
        public_base = (cfg.get("oauth_redirect_base") or "").rstrip("/")
        if not public_base:
            raise HTTPException(400, "oauth_redirect_base not configured")

        # Handle delayed mode — just schedule and return
        if mode == "delayed":
            await database.execute(
                "UPDATE outputs SET tiktok_retry_after = NOW() + INTERVAL '6 hours', "
                "tiktok_error = NULL WHERE id = ?",
                (output_id,),
            )
            await database.commit()
            return {"ok": True, "mode": "delayed", "message": "TikTok retry scheduled in 6 hours"}

        # Build public video URLs
        _video_t = secrets.token_urlsafe(6)
        legacy_video_path = out.get("video_path")

        def _public_video_url(p=None):
            path = (out.get(f"{p}_video_path") if p else None) or legacy_video_path
            if not path:
                return None
            rel = path.lstrip("./")
            enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
            return f"{public_base}/api/files/{enc}?for={account['id']}&t={_video_t}"

        # Build TikTok slide URLs
        slide_urls: list[str] = []
        slides_dir = out.get("slides_dir")
        if slides_dir and Path(slides_dir).exists():
            _t = secrets.token_urlsafe(6)
            for f in sorted(Path(slides_dir).iterdir()):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and "_9x16" not in f.stem:
                    rel = str(f).lstrip("./")
                    enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
                    slide_urls.append(
                        f"{public_base}/api/files-jpg/{enc}?for={account['id']}&t={_t}"
                    )

        # Refresh tokens
        async def _fresh_token(platform_name: str):
            token_local = account.get(f"{platform_name}_token")
            if not token_local:
                return None
            exp = account.get(f"{platform_name}_expires_at")
            refresh = account.get(f"{platform_name}_refresh_token")
            needs_refresh = False
            if exp:
                try:
                    exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
                    if exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=2):
                        needs_refresh = True
                except Exception:
                    pass
            if not needs_refresh or not refresh:
                return token_local
            if platform_name == "facebook":
                provider = "meta"
            elif platform_name == "instagram":
                provider = "meta" if account.get("facebook_token") else "instagram"
            else:
                provider = platform_name
            cid = cfg.get(f"oauth_{provider}_client_id", "")
            csec = cfg.get(f"oauth_{provider}_client_secret", "")
            if not cid or not csec:
                return token_local
            try:
                refreshed = await oauth_svc.refresh_access_token(
                    provider, refresh, cid, csec,
                    proxy_url=account.get("proxy_url") or None,
                )
            except Exception:
                return token_local
            new_token = refreshed.get("access_token")
            if not new_token:
                return token_local
            updates_tok: dict = {f"{platform_name}_token": new_token}
            if refreshed.get("refresh_token"):
                updates_tok[f"{platform_name}_refresh_token"] = refreshed["refresh_token"]
            if refreshed.get("expires_in"):
                new_exp = datetime.now(timezone.utc) + timedelta(seconds=int(refreshed["expires_in"]))
                updates_tok[f"{platform_name}_expires_at"] = new_exp.isoformat()
            try:
                await db.update_account(database, account["id"], **updates_tok)
            except Exception:
                pass
            return new_token

        caption = out.get("caption") or ""
        account_proxy = account.get("proxy_url") or None
        per_platform: dict = {}
        any_success = False

        adapters = {"tiktok": _tt, "youtube": _yt, "instagram": _ig, "facebook": _fb}

        for plat in ("tiktok", "youtube", "instagram", "facebook"):
            # Only retry platforms that have a stored error
            if not out.get(f"{plat}_error"):
                continue
            # draft/delayed modes only apply to TikTok
            if mode in ("draft",) and plat != "tiktok":
                continue

            adapter = adapters[plat]
            token = await _fresh_token(plat)
            if not token:
                per_platform[plat] = {"status": "skipped", "reason": "not connected"}
                continue

            try:
                if plat == "tiktok":
                    if mode == "draft" or out.get("tiktok_post_as_draft"):
                        tt_kwargs: dict = {"post_mode": "INBOX"}
                    else:
                        privacy = out.get("tiktok_privacy_level")
                        if not privacy:
                            per_platform[plat] = {"status": "failed", "error": "TikTok privacy not set"}
                            continue
                        tt_kwargs = {
                            "post_mode": "DIRECT_POST",
                            "privacy_level": privacy.upper(),
                            "disable_comment": not bool(out.get("tiktok_allow_comment")),
                            "disable_duet":    not bool(out.get("tiktok_allow_duet")),
                            "disable_stitch":  not bool(out.get("tiktok_allow_stitch")),
                            "brand_content_toggle": bool(out.get("tiktok_disclose_branded_content")),
                            "brand_organic_toggle": bool(out.get("tiktok_disclose_your_brand")),
                        }
                    if slide_urls:
                        slideshow_kwargs = {k: v for k, v in tt_kwargs.items()
                                            if k not in ("disable_duet", "disable_stitch")}
                        res = await _tt.upload_photo_slideshow(
                            token, slide_urls, caption,
                            proxy_url=account_proxy, **slideshow_kwargs,
                        )
                    else:
                        plat_url = _public_video_url(None)
                        if not plat_url:
                            per_platform[plat] = {"status": "skipped", "reason": "no video"}
                            continue
                        res = await adapter.upload_video(
                            token, plat_url, caption,
                            proxy_url=account_proxy, **tt_kwargs,
                        )
                else:
                    plat_url = _public_video_url(plat)
                    if not plat_url:
                        per_platform[plat] = {"status": "skipped", "reason": "no video"}
                        continue
                    plat_kwargs: dict = {}
                    if plat == "facebook" and account.get("facebook_user_id"):
                        plat_kwargs["page_id"] = account["facebook_user_id"]
                    if plat == "instagram" and account.get("instagram_user_id"):
                        plat_kwargs["ig_user_id"] = account["instagram_user_id"]
                    res = await adapter.upload_video(
                        token, plat_url, caption,
                        proxy_url=account_proxy, **plat_kwargs,
                    )

                per_platform[plat] = {
                    "status": "posted",
                    "platform_post_id": res.get("platform_post_id"),
                    **({"draft": True} if res.get("draft") else {}),
                }
                any_success = True
                try:
                    upd: dict = {f"{plat}_posted": True, f"{plat}_error": None}
                    if res.get("draft"):
                        upd["posted_as_draft"] = True
                    await db.update_output(database, output_id, **upd)
                except Exception:
                    pass

            except PostingError as e:
                err_msg = str(e)[:300]
                # Auto-fallback to INBOX when TikTok rejects DIRECT_POST for unaudited apps
                if plat == "tiktok" and "unaudited_client_can_only_post_to_private_accounts" in err_msg.lower():
                    try:
                        if slide_urls:
                            res = await _tt.upload_photo_slideshow(
                                token, slide_urls, caption,
                                proxy_url=account_proxy, post_mode="INBOX",
                            )
                        else:
                            _pu = _public_video_url(None)
                            if not _pu:
                                raise RuntimeError("no_video")
                            res = await _tt.upload_video(
                                token, _pu, caption,
                                proxy_url=account_proxy, post_mode="INBOX",
                            )
                        per_platform[plat] = {
                            "status": "posted", "draft": True,
                            "platform_post_id": res.get("platform_post_id"),
                        }
                        any_success = True
                        try:
                            await db.update_output(database, output_id, **{
                                f"{plat}_posted": True, f"{plat}_error": None,
                                "posted_as_draft": True,
                            })
                        except Exception:
                            pass
                        continue
                    except Exception:
                        pass  # fall through to record original error
                per_platform[plat] = {"status": "failed", "error": err_msg, "friendly_error": _friendly_error(err_msg)}
                try:
                    await db.update_output(database, output_id, **{f"{plat}_error": err_msg})
                except Exception:
                    pass
            except Exception as e:
                err_msg = f"{type(e).__name__}: {str(e)[:250]}"
                per_platform[plat] = {"status": "failed", "error": err_msg, "friendly_error": _friendly_error(err_msg)}
                try:
                    await db.update_output(database, output_id, **{f"{plat}_error": err_msg})
                except Exception:
                    pass

        # If any platform succeeded and the post was 'failed', promote it
        if any_success and out.get("post_status") == "failed":
            try:
                await database.execute(
                    "UPDATE posts SET status = 'posted' WHERE id = ? AND status = 'failed'",
                    (out["post_id"],),
                )
                await database.commit()
            except Exception:
                pass

        return {
            "ok": any_success,
            "mode": mode,
            "output_id": output_id,
            "platforms": per_platform,
        }
    finally:
        await database.close()


@app.delete("/api/posts/{post_id}/failed-outputs")
async def clear_failed_outputs(post_id: int, user: dict = Depends(get_current_user)):
    """Clear all platform error messages on this post's outputs.

    Does NOT delete the outputs — just NULLs every *_error column so
    they disappear from FailedOutputsSection. Ownership-checked.
    """
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        await database.execute(
            """
            UPDATE outputs
            SET tiktok_error = NULL, youtube_error = NULL,
                instagram_error = NULL, facebook_error = NULL,
                tiktok_retry_after = NULL
            WHERE post_id = ?
            """,
            (post_id,),
        )
        await database.commit()
        return {"ok": True}
    finally:
        await database.close()


@app.patch("/api/outputs/{output_id}/tiktok")
async def update_output_tiktok(
    output_id: int,
    data: OutputTikTokSettings,
    user: dict = Depends(get_current_user),
):
    """Save per-(post, variation) TikTok Direct Post API settings.

    Stamps `tiktok_consent_at = now()` on every save: TikTok requires the
    Music Usage Confirmation declaration to appear before the publish
    button, and the user clicking Save here is the moment they "agree to
    TikTok's Music Usage Confirmation" (and Branded Content Policy when
    that disclosure option is on).
    """
    database = await db.get_db()
    try:
        # Load output → post → brand for ownership.
        from sqlalchemy import select as _select
        from database import Output as _Output
        rows = await database.session.execute(
            _select(_Output).where(_Output.id == output_id)
        )
        out_row = rows.scalar_one_or_none()
        if not out_row:
            raise HTTPException(404, "Output not found")
        out_d = {c.name: getattr(out_row, c.name) for c in out_row.__table__.columns}
        post = await db.get_post(database, out_d["post_id"])
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        updates: dict = {}
        for field, value in data.model_dump(exclude_unset=True).items():
            updates[field] = value

        # Validate privacy when set; ignore null (no-default rule).
        if "tiktok_privacy_level" in updates and updates["tiktok_privacy_level"] is not None:
            lvl = updates["tiktok_privacy_level"].upper()
            if lvl not in {"SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"}:
                raise HTTPException(400, "Invalid tiktok_privacy_level")
            updates["tiktok_privacy_level"] = lvl

        # Cross-rule guard: branded content cannot ride with SELF_ONLY.
        # Read the merged final state (current + incoming) so a partial
        # PATCH can't sneak past.
        merged = {**out_d, **updates}
        if (
            merged.get("tiktok_disclose_branded_content")
            and (merged.get("tiktok_privacy_level") or "").upper() == "SELF_ONLY"
        ):
            raise HTTPException(
                400,
                "TikTok rejects branded content with SELF_ONLY privacy. "
                "Pick a non-private level or uncheck Branded content.",
            )

        # Stamp the consent moment. The UI surfaces the music-usage /
        # branded-content declarations directly above the Save button.
        # MUST be naive UTC — the column is TIMESTAMP WITHOUT TIME ZONE.
        updates["tiktok_consent_at"] = _naive_utc_now()

        try:
            await db.update_output(database, output_id, **updates)
        except Exception as e:
            # Log full error to error_logs; surface a short detail in the
            # response so the toast on the client says something useful.
            await db.log_error(
                database, source="api",
                message=f"PATCH /api/outputs/{output_id}/tiktok: {e}",
                traceback=traceback.format_exc(),
                user_id=user.get("id"),
            )
            raise HTTPException(
                500,
                f"Save failed: {str(e)[:160]} (see /admin → Errors for full traceback)",
            )
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# SCHEDULING
# =============================================

@app.put("/api/posts/{post_id}/schedule")
async def schedule_post(post_id: int, data: PostSchedule, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        updates = {}
        if data.scheduled_time is not None:
            updates["scheduled_time"] = data.scheduled_time
            updates["status"] = "scheduled"
        if data.caption is not None:
            updates["caption"] = data.caption
        if data.music_track_id is not None:
            updates["music_track_id"] = data.music_track_id
        if updates:
            await db.update_post(database, post_id, **updates)
        post = await db.get_post(database, post_id)
        return row_to_dict(post)
    finally:
        await database.close()

@app.post("/api/posts/{post_id}/unschedule")
async def unschedule_post(post_id: int, user: dict = Depends(get_current_user)):
    """Revert a scheduled post back to draft, clearing its scheduled time."""
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)
        await db.update_post(database, post_id, status="draft", scheduled_time=None, reminder_sent_at=None)
        return {"ok": True}
    finally:
        await database.close()


@app.get("/api/schedule")
async def get_schedule(brand_id: Optional[int] = None, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        query = "SELECT p.*, b.name as brand_name, b.slug as brand_slug FROM posts p JOIN brands b ON p.brand_id = b.id WHERE p.status IN ('scheduled', 'generating', 'posting') AND b.user_id = ?"
        params = [user["id"]]
        if brand_id:
            query += " AND p.brand_id = ?"
            params.append(brand_id)
        query += " ORDER BY p.date, p.scheduled_time"
        cursor = await database.execute(query, params)
        posts = await cursor.fetchall()
        return rows_to_list(posts)
    finally:
        await database.close()


# =============================================
# MUSIC (user-scoped)
# =============================================

@app.get("/api/music")
async def list_music(
    platform: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """List music tracks available to the user.

    Pass `?platform=youtube|instagram|facebook` to filter to tracks flagged
    as commercial-safe for that platform (via music_tracks.platforms_allowed).
    """
    database = await db.get_db()
    try:
        tracks = await db.get_music_tracks(database, user_id=user["id"])
        rows = rows_to_list(tracks)
        if platform:
            p = platform.lower()
            rows = [
                t for t in rows
                if p in {s.strip().lower() for s in (t.get("platforms_allowed") or "").split(",") if s.strip()}
            ]
        return rows
    finally:
        await database.close()


class MusicTrackUpdate(BaseModel):
    platforms_allowed: Optional[str] = None  # CSV, e.g. "youtube,instagram"
    name: Optional[str] = None
    genre: Optional[str] = None


@app.put("/api/music/{track_id}")
async def update_music(track_id: int, data: MusicTrackUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cur = await database.execute("SELECT * FROM music_tracks WHERE id = ?", (track_id,))
        track = await cur.fetchone()
        if not track:
            raise HTTPException(404, "Track not found")
        if user["role"] != "admin" and track["user_id"] != user["id"]:
            raise HTTPException(403, "Access denied")
        updates: dict = {}
        if data.platforms_allowed is not None:
            allowed = {"youtube", "instagram", "facebook", "tiktok"}
            csv = ",".join(
                sorted({s.strip().lower() for s in data.platforms_allowed.split(",") if s.strip().lower() in allowed})
            )
            updates["platforms_allowed"] = csv
        if data.name is not None:
            updates["name"] = data.name
        if data.genre is not None:
            updates["genre"] = data.genre
        if updates:
            await db.update_music_track(database, track_id, **updates)
        cur2 = await database.execute("SELECT * FROM music_tracks WHERE id = ?", (track_id,))
        return row_to_dict(await cur2.fetchone())
    finally:
        await database.close()

@app.post("/api/music")
async def upload_music(
    name: str = Form(...),
    genre: str = Form(None),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    database = await db.get_db()
    try:
        save_dir = Path("music")
        save_dir.mkdir(exist_ok=True)
        ext = Path(file.filename).suffix or ".mp3"
        safe_name = "".join(c for c in name if c.isalnum() or c in "._- ").strip()
        save_path = save_dir / f"{safe_name}{ext}"

        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        track_id = await db.create_music_track(
            database, name, str(save_path), genre=genre, is_custom=True,
            user_id=user["id"]
        )

        cursor = await database.execute("SELECT * FROM music_tracks WHERE id = ?", (track_id,))
        return row_to_dict(await cursor.fetchone())
    finally:
        await database.close()

@app.delete("/api/music/{track_id}")
async def delete_music(track_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute("SELECT * FROM music_tracks WHERE id = ?", (track_id,))
        track = await cursor.fetchone()
        if not track:
            raise HTTPException(404, "Track not found")
        if user["role"] != "admin" and track["user_id"] != user["id"]:
            raise HTTPException(403, "Access denied")
        await db.delete_music_track(database, track_id)
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# DOWNLOADS
# =============================================

@app.get("/api/posts/{post_id}/download/{account_id}")
async def download_account_output(post_id: int, account_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        cursor = await database.execute(
            "SELECT * FROM outputs WHERE post_id = ? AND account_id = ?",
            (post_id, account_id)
        )
        output = await cursor.fetchone()
        if not output or not output["slides_dir"]:
            raise HTTPException(404, "Output not found")

        out_dir = Path(output["slides_dir"]).parent
        if not out_dir.exists():
            raise HTTPException(404, "Output directory not found")

        zip_path = str(out_dir) + ".zip"
        shutil.make_archive(str(out_dir), "zip", str(out_dir))

        return FileResponse(zip_path, filename=f"{out_dir.name}.zip", media_type="application/zip")
    finally:
        await database.close()

@app.get("/api/posts/{post_id}/download")
async def download_all_outputs(post_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        post = await db.get_post(database, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        await verify_brand_ownership(post["brand_id"], user)

        outputs = await db.get_outputs(database, post_id)
        if not outputs:
            raise HTTPException(404, "No outputs found")

        brand = await db.get_brand(database, post["brand_id"])

        base_dir = Path("output") / brand["slug"] / post["date"]
        if not base_dir.exists():
            raise HTTPException(404, "Output directory not found")

        zip_path = str(base_dir) + f"_post_{post['id']}.zip"
        shutil.make_archive(zip_path.replace(".zip", ""), "zip", str(base_dir))

        return FileResponse(zip_path, filename=Path(zip_path).name, media_type="application/zip")
    finally:
        await database.close()


# =============================================
# FILE SERVING (public — files are behind auth-gated paths anyway)
# =============================================

@app.get("/api/files-jpg/{file_path:path}")
async def serve_file_as_jpeg(file_path: str, for_: Optional[int] = Query(None, alias="for")):
    """Serve any image file re-encoded as JPEG with per-account fingerprint
    diversity, used by TikTok's photo slideshow API (which rejects PNG).

    Three things vary based on `?for={account_id}`:

    1. JPEG encoder params (quality / subsampling / optimize / progressive)
       are deterministically derived from account_id, so two accounts'
       pulls of the same source PNG produce different bytes — different
       compressed-size, different DCT coefficient distribution. Same
       account always gets the same encoding (cache stable per account).

    2. Synthetic EXIF (Make / Model / DateTimeOriginal / Software) is
       embedded before encode. Without it, our slides scream "synthetic
       JPEG with no metadata" — TikTok's spam clustering can fingerprint
       on the absence of EXIF. A phone-captured image always has it.

    3. Response headers: `Cache-Control: no-store` so TikTok always
       fetches fresh bytes (DateTimeOriginal advances per request) and
       Content-Disposition with a phone-style filename.

    `?for=` is optional for back-compat (other callers — like browser
    previews — still get the legacy behaviour).
    """
    from io import BytesIO
    from PIL import Image
    import piexif

    full_path = Path(file_path)
    if not full_path.exists():
        for base in [Path("uploads"), Path("output"), Path("music")]:
            candidate = base / file_path
            if candidate.exists():
                full_path = candidate
                break
    if not full_path.exists():
        raise HTTPException(404, "File not found")

    # Per-account JPEG params. Deterministic from account_id so the same
    # account → same encoding (clusters within an account look like one
    # device's output). Different accounts → different fingerprints.
    if for_ is not None:
        seed = for_
        quality      = (86, 88, 90, 92, 94)[seed % 5]
        subsampling  = (0, 2)[seed % 2]
        optimize     = bool((seed >> 1) & 1)
        progressive  = bool((seed >> 2) & 1)
        # Synthetic device pool — three majors, several plausible models
        # each. The pair (make, model) is stable per account.
        DEVICES = [
            ("Apple",   "iPhone 15"),
            ("Apple",   "iPhone 14 Pro"),
            ("Apple",   "iPhone 13"),
            ("samsung", "SM-S928U"),     # Galaxy S24 Ultra
            ("samsung", "SM-S921U"),     # Galaxy S24
            ("Google",  "Pixel 8"),
            ("Google",  "Pixel 7a"),
        ]
        make, model = DEVICES[seed % len(DEVICES)]
        software_pool = {
            "Apple":   ["17.5.1", "17.6", "18.0"],
            "samsung": ["One UI 6.1", "One UI 6.0"],
            "Google":  ["TQ3A.230901.001", "TQ3A.230705.001"],
        }
        software = software_pool[make][seed % len(software_pool[make])]
    else:
        quality, subsampling, optimize, progressive = 92, 2, True, False
        make, model, software = None, None, None

    # Pillow open + encode is CPU-bound. Run in a thread so the event loop
    # stays free for other requests while TikTok pulls the JPEG.
    _full_path = full_path
    _for = for_
    _make, _model, _software = make, model, software
    _quality, _subsampling, _optimize, _progressive = quality, subsampling, optimize, progressive

    def _encode_jpeg():
        _img = Image.open(_full_path)
        if _img.mode not in ("RGB", "L"):
            _img = _img.convert("RGB")

        _exif_bytes = b""
        if _for is not None and _make and _model:
            from random import randint
            shot = datetime.now(timezone.utc) - timedelta(seconds=randint(15 * 60, 6 * 3600))
            shot_str = shot.strftime("%Y:%m:%d %H:%M:%S").encode("ascii")
            zeroth = {
                piexif.ImageIFD.Make:     _make.encode("ascii"),
                piexif.ImageIFD.Model:    _model.encode("ascii"),
                piexif.ImageIFD.Software: _software.encode("ascii"),
                piexif.ImageIFD.DateTime: shot_str,
                piexif.ImageIFD.Orientation: 1,
            }
            exif_dict = {
                "0th": zeroth,
                "Exif": {
                    piexif.ExifIFD.DateTimeOriginal:  shot_str,
                    piexif.ExifIFD.DateTimeDigitized: shot_str,
                },
                "GPS": {},
                "1st": {},
                "thumbnail": None,
            }
            try:
                _exif_bytes = piexif.dump(exif_dict)
            except Exception:
                _exif_bytes = b""

        _buf = BytesIO()
        _save_kwargs = {
            "format": "JPEG",
            "quality": _quality,
            "subsampling": _subsampling,
            "optimize": _optimize,
            "progressive": _progressive,
        }
        if _exif_bytes:
            _save_kwargs["exif"] = _exif_bytes
        _img.save(_buf, **_save_kwargs)
        return _buf.getvalue()

    try:
        jpeg_bytes = await asyncio.to_thread(_encode_jpeg)
    except Exception as e:
        raise HTTPException(500, f"Could not convert image: {e}")

    # Filename hint that looks like a phone-camera capture.
    headers = {"Cache-Control": "no-store" if for_ is not None else "public, max-age=300"}
    if for_ is not None:
        # Stable per (account, source-path) so the same slide shows the
        # same filename on retry; prevents TikTok seeing wildly different
        # filenames for the same logical slide image.
        from hashlib import md5
        fname_seed = md5(f"{for_}:{file_path}".encode()).hexdigest()[:4].upper()
        headers["Content-Disposition"] = f'inline; filename="IMG_{fname_seed}.JPG"'

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers=headers,
    )


@app.get("/api/files/{file_path:path}")
async def serve_file(file_path: str, for_: Optional[int] = Query(None, alias="for")):
    full_path = Path(file_path)
    if not full_path.exists():
        for base in [Path("uploads"), Path("output"), Path("music")]:
            candidate = base / file_path
            if candidate.exists():
                full_path = candidate
                break
    if not full_path.exists():
        raise HTTPException(404, "File not found")

    # When ?for={account_seed} is set AND this is a video, return a
    # per-account remuxed copy with synthetic phone-grade container
    # metadata. Both Brand /posts/new and the Clipping scheduler append
    # this query string when handing a URL to a platform adapter, so
    # YouTube / TikTok / IG / FB each see a different .mp4 fingerprint
    # per account. Browser previews (no ?for=) get raw bytes unchanged.
    if for_ is not None and full_path.suffix.lower() in (".mp4", ".mov", ".m4v"):
        try:
            data = await _remux_video_with_account_metadata(full_path, int(for_))
            return Response(
                content=data,
                media_type="video/mp4",
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": f'inline; filename="IMG_{int(for_):04d}.MP4"',
                },
            )
        except Exception:
            # Fall through to raw on any unexpected error so we never
            # break a post over a metadata-fingerprint nicety.
            pass

    # Force browsers to revalidate — regenerated slides overwrite the same filename,
    # so without no-cache the old image would stick around after a regenerate.
    return FileResponse(
        str(full_path),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# =============================================
# USER SETTINGS (per-user API keys)
# =============================================

@app.get("/api/user-settings")
async def get_user_settings(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        return await db.get_user_settings(database, user["id"])
    finally:
        await database.close()

@app.put("/api/user-settings")
async def update_user_settings(data: SettingUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        await db.set_user_setting(database, user["id"], data.key, data.value)
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# GLOBAL SETTINGS (admin only for write, readable by all auth users)
# =============================================

_PER_USER_SETTING_KEYS = {"anthropic_api_key", "openai_api_key"}

@app.get("/api/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute("SELECT * FROM settings")
        rows = await cursor.fetchall()
        cfg = {r["key"]: r["value"] for r in rows}
        # Overlay per-user API keys on top of global defaults
        user_map = await db.get_user_settings(database, user["id"])
        for k in _PER_USER_SETTING_KEYS:
            if k in user_map:
                cfg[k] = user_map[k]
        return cfg
    finally:
        await database.close()

@app.put("/api/settings")
async def update_settings(data: SettingUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        if data.key in _PER_USER_SETTING_KEYS:
            # Store API keys per-user so different users have independent keys
            await db.set_user_setting(database, user["id"], data.key, data.value or "")
        else:
            await db.set_setting(database, data.key, data.value)
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# STATS
# =============================================

@app.get("/api/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        async def _count(sql: str, params: tuple = ()) -> int:
            cur = await database.execute(sql, params) if params else await database.execute(sql)
            row = await cur.fetchone()
            return int(row["count"]) if row else 0

        today = datetime.now().strftime("%Y-%m-%d")
        if user["role"] == "admin":
            brands_n = await _count("SELECT COUNT(*) as count FROM brands")
            posts_today_n = await _count("SELECT COUNT(*) as count FROM posts WHERE date = ?", (today,))
            scheduled_n = await _count("SELECT COUNT(*) as count FROM posts WHERE status = 'scheduled'")
            total_posts_n = await _count("SELECT COUNT(*) as count FROM posts")
            accounts_n = await _count("SELECT COUNT(*) as count FROM accounts")
            artists_n = await _count("SELECT COUNT(*) as count FROM artists")
            variations_n = await _count("SELECT COUNT(*) as count FROM artist_accounts")
            clips_n = await _count("SELECT COUNT(*) as count FROM clips")
            clip_posts_n = await _count("SELECT COUNT(*) as count FROM clip_posts WHERE status = 'posted'")
            clip_scheduled_n = await _count("SELECT COUNT(*) as count FROM clip_posts WHERE status = 'scheduled'")
        else:
            uid = user["id"]
            brands_n = await _count("SELECT COUNT(*) as count FROM brands WHERE user_id = ?", (uid,))
            posts_today_n = await _count(
                "SELECT COUNT(*) as count FROM posts p JOIN brands b ON p.brand_id = b.id WHERE p.date = ? AND b.user_id = ?",
                (today, uid),
            )
            scheduled_n = await _count(
                "SELECT COUNT(*) as count FROM posts p JOIN brands b ON p.brand_id = b.id WHERE p.status = 'scheduled' AND b.user_id = ?",
                (uid,),
            )
            total_posts_n = await _count(
                "SELECT COUNT(*) as count FROM posts p JOIN brands b ON p.brand_id = b.id WHERE b.user_id = ?",
                (uid,),
            )
            accounts_n = await _count(
                "SELECT COUNT(*) as count FROM accounts a JOIN brands b ON a.brand_id = b.id WHERE b.user_id = ?",
                (uid,),
            )
            artists_n = await _count("SELECT COUNT(*) as count FROM artists WHERE user_id = ?", (uid,))
            variations_n = await _count(
                "SELECT COUNT(*) as count FROM artist_accounts aa JOIN artists a ON aa.artist_id = a.id WHERE a.user_id = ?",
                (uid,),
            )
            clips_n = await _count(
                "SELECT COUNT(*) as count FROM clips c JOIN artists a ON c.artist_id = a.id WHERE a.user_id = ?",
                (uid,),
            )
            clip_posts_n = await _count(
                "SELECT COUNT(*) as count FROM clip_posts cp JOIN artists a ON cp.artist_id = a.id WHERE a.user_id = ? AND cp.status = 'posted'",
                (uid,),
            )
            clip_scheduled_n = await _count(
                "SELECT COUNT(*) as count FROM clip_posts cp JOIN artists a ON cp.artist_id = a.id WHERE a.user_id = ? AND cp.status = 'scheduled'",
                (uid,),
            )

        return {
            "brands": brands_n,
            "accounts": accounts_n,
            "posts_today": posts_today_n,
            "scheduled": scheduled_n,
            "total_posts": total_posts_n,
            "artists": artists_n,
            "variations": variations_n,
            "clips": clips_n,
            "clip_posts": clip_posts_n,
            "clip_scheduled": clip_scheduled_n,
        }
    finally:
        await database.close()


# =============================================
# CLIPPING ROUTES — Artists, Variations, Clips
# =============================================

from services import gdrive as gdrive_svc


def _artist_upload_dir(artist: dict) -> Path:
    d = Path("uploads") / "artists" / artist["slug"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _artist_account_dict(row) -> dict:
    """Strip raw token values but expose booleans for connection status."""
    d = dict(row)
    for p in ("tiktok", "youtube", "instagram", "facebook"):
        d[f"{p}_connected"] = bool(d.get(f"{p}_token"))
        # drop raw tokens from the API response
        for k in (f"{p}_token", f"{p}_refresh_token"):
            d.pop(k, None)
    return d


@app.get("/api/artists")
async def list_artists(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        artists = await db.get_artists(database, user_id=user["id"])
        result = []
        for a in artists:
            variations = await db.get_artist_accounts(database, a["id"])
            clips = await db.get_clips(database, a["id"])
            posts = await db.get_clip_posts(database, artist_id=a["id"])
            # Mirror dashboard logic exactly:
            # - views_total: ALL posted rows incl. deleted (so view counts never
            #   drop when a video is removed from the platform)
            # - posts_total: non-deleted, deduped on (clip_id, account, platform)
            views_total = 0
            posts_total = 0
            _seen: set[tuple] = set()
            for p in posts:
                if p.get("status") != "posted":
                    continue
                # Views include deleted posts — same as dashboard.
                views_total += int(p.get("view_count") or 0)
                # Exclude deleted posts and TikTok inbox drafts (posted_as_draft=TRUE).
                # NULL-clip discovery rows (phone-published videos) DO count.
                if p.get("deleted_at") or p.get("posted_as_draft"):
                    continue
                _key = (
                    p.get("clip_id") if p.get("clip_id") is not None else p.get("id"),
                    p.get("artist_account_id"),
                    p.get("platform"),
                )
                if _key in _seen:
                    continue
                _seen.add(_key)
                posts_total += 1
            result.append({
                **dict(a),
                "variations_count": len(variations),
                "clips_count": len(clips),
                "posts_count": posts_total,
                "views_total": views_total,
            })
        return result
    finally:
        await database.close()


@app.post("/api/artists")
async def create_artist(data: ArtistCreate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        aid = await db.create_artist(
            database, name=data.name, slug=data.slug, user_id=user["id"],
            timezone=data.timezone, posts_per_day=data.posts_per_day,
            window_start=data.window_start, window_end=data.window_end,
        )
        artist = await db.get_artist(database, aid)
        return row_to_dict(artist)
    finally:
        await database.close()


@app.get("/api/artists/by-slug/{slug}")
async def get_artist_by_slug_route(slug: str, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        artist = await db.get_artist_by_slug(database, user["id"], slug)
        if not artist:
            raise HTTPException(404, "Artist not found")
        artist_id = artist["id"]
        variations = await db.get_artist_accounts(database, artist_id)
        clips = await db.get_clips(database, artist_id)
        posts = await db.get_clip_posts(database, artist_id=artist_id, limit=50)
        return {
            **dict(artist),
            "variations": [_artist_account_dict(v) for v in variations],
            "clips": rows_to_list(clips),
            "recent_posts": rows_to_list(posts),
        }
    finally:
        await database.close()


@app.get("/api/artists/{artist_id}")
async def get_artist_detail(artist_id: int, user: dict = Depends(get_current_user)):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        variations = await db.get_artist_accounts(database, artist_id)
        clips = await db.get_clips(database, artist_id)
        posts = await db.get_clip_posts(database, artist_id=artist_id, limit=50)
        return {
            **artist,
            "variations": [_artist_account_dict(v) for v in variations],
            "clips": rows_to_list(clips),
            "recent_posts": rows_to_list(posts),
        }
    finally:
        await database.close()


@app.put("/api/artists/{artist_id}")
async def update_artist_route(artist_id: int, data: ArtistUpdate, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if "gdrive_folder_url" in updates:
            folder_id = gdrive_svc.parse_folder_id(updates["gdrive_folder_url"])
            updates["gdrive_folder_id"] = folder_id
        if updates:
            await db.update_artist(database, artist_id, **updates)
        artist = await db.get_artist(database, artist_id)
        return row_to_dict(artist)
    finally:
        await database.close()


@app.delete("/api/artists/{artist_id}")
async def delete_artist_route(artist_id: int, user: dict = Depends(get_current_user)):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        await db.delete_artist(database, artist_id)
    finally:
        await database.close()
    upload_dir = Path("uploads") / "artists" / artist["slug"]
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
    return {"ok": True}


# --- Variations (artist accounts) ---

@app.post("/api/artists/{artist_id}/variations")
async def create_variation_route(artist_id: int, data: VariationCreate, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        kwargs = {k: v for k, v in data.model_dump().items() if v is not None and k != "name"}
        vid = await db.create_artist_account(database, artist_id, data.name, **kwargs)
        row = await db.get_artist_account(database, vid)
        return _artist_account_dict(row)
    finally:
        await database.close()


@app.put("/api/variations/{variation_id}")
async def update_artist_variation(variation_id: int, data: VariationUpdateArtist, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        row = await db.get_artist_account(database, variation_id)
        if not row:
            raise HTTPException(404, "Variation not found")
        await _verify_artist_ownership(row["artist_id"], user)
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        # Normalise empty-string paused_reason to NULL so IS NULL checks work
        if "paused_reason" in updates and updates["paused_reason"] == "":
            updates["paused_reason"] = None
        if updates:
            await db.update_artist_account(database, variation_id, **updates)
        row = await db.get_artist_account(database, variation_id)
        return _artist_account_dict(row)
    finally:
        await database.close()


@app.patch("/api/variations/{variation_id}/tiktok")
async def update_variation_tiktok(
    variation_id: int,
    data: TikTokSettingsPayload,
    user: dict = Depends(get_current_user),
):
    """Save per-variation TikTok Direct Post API settings (Clipping pipeline).

    Mirrors the Brand-side PATCH /api/outputs/{id}/tiktok with the same
    validation: privacy level constrained, branded + SELF_ONLY rejected
    (checks merged state so a partial PATCH can't sneak past), and
    tiktok_consent_at stamped server-side as the user's music-usage /
    branded-content acknowledgement moment.
    """
    database = await db.get_db()
    try:
        row = await db.get_artist_account(database, variation_id)
        if not row:
            raise HTTPException(404, "Variation not found")
        await _verify_artist_ownership(row["artist_id"], user)
        row_d = dict(row)

        updates: dict = {}
        for field, value in data.model_dump(exclude_unset=True).items():
            updates[field] = value

        if "tiktok_privacy_level" in updates and updates["tiktok_privacy_level"] is not None:
            lvl = updates["tiktok_privacy_level"].upper()
            if lvl not in {"SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"}:
                raise HTTPException(400, "Invalid tiktok_privacy_level")
            updates["tiktok_privacy_level"] = lvl

        merged = {**row_d, **updates}
        if (
            merged.get("tiktok_disclose_branded_content")
            and (merged.get("tiktok_privacy_level") or "").upper() == "SELF_ONLY"
        ):
            raise HTTPException(
                400,
                "TikTok rejects branded content with SELF_ONLY privacy. "
                "Pick a non-private level or uncheck Branded content.",
            )

        # MUST be naive UTC — tiktok_consent_at is TIMESTAMP WITHOUT TIME ZONE.
        updates["tiktok_consent_at"] = _naive_utc_now()
        try:
            await db.update_artist_account(database, variation_id, **updates)
        except Exception as e:
            await db.log_error(
                database, source="api",
                message=f"PATCH /api/variations/{variation_id}/tiktok: {e}",
                traceback=traceback.format_exc(),
                user_id=user.get("id"),
            )
            raise HTTPException(
                500,
                f"Save failed: {str(e)[:160]} (see /admin → Errors for full traceback)",
            )
        fresh = await db.get_artist_account(database, variation_id)
        return _artist_account_dict(fresh)
    finally:
        await database.close()


@app.post("/api/variations/{variation_id}/refresh-profile")
async def refresh_variation_profile(variation_id: int, user: dict = Depends(get_current_user)):
    """Re-run profile handle lookup for every connected platform on a variation.

    For each platform with a stored token, call the platform's me/profile
    endpoint and update the `{platform}_handle` column. Returns a per-platform
    status so the UI can show which ones succeeded / why any failed (e.g.
    TikTok's 'scope_not_authorized' when `user.info.basic` wasn't granted).
    """
    database = await db.get_db()
    try:
        row = await db.get_artist_account(database, variation_id)
        if not row:
            raise HTTPException(404, "Variation not found")
        await _verify_artist_ownership(row["artist_id"], user)
        v = dict(row)

        status: dict[str, dict] = {}
        updates: dict = {}
        # Meta FB Login flow covers IG+FB in one call via facebook_token.
        # Standalone IG Login returns only an instagram_token with no FB page
        # — query graph.instagram.com/me via the "instagram" provider branch.
        platform_specs = [
            ("tiktok", "tiktok", v.get("tiktok_token")),
            ("youtube", "youtube", v.get("youtube_token")),
        ]
        if v.get("facebook_token"):
            platform_specs.append(("meta", "facebook", v.get("facebook_token")))
        elif v.get("instagram_token"):
            platform_specs.append(("instagram", "instagram", v.get("instagram_token")))
        for api_platform, display_key, token in platform_specs:
            if not token:
                status[display_key] = {"status": "skipped", "reason": "not connected"}
                continue
            try:
                handles = await oauth_svc.fetch_profile_handles_strict(api_platform, token)
                if handles:
                    updates.update(handles)
                    status[display_key] = {"status": "ok", "handles": handles}
                else:
                    status[display_key] = {"status": "empty", "reason": "no username returned"}
            except oauth_svc.ProfileFetchError as e:
                msg = str(e)[:300]
                status[display_key] = {"status": "failed", "error": msg}
                await db.log_error(
                    database, source=f"oauth.profile.{api_platform}",
                    message=msg, context=f"variation_id={variation_id}",
                )
            except Exception as e:
                status[display_key] = {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:250]}"}

        if updates:
            await db.update_artist_account(database, variation_id, **updates)
        row = await db.get_artist_account(database, variation_id)
        return {"variation": _artist_account_dict(row), "results": status}
    finally:
        await database.close()


@app.delete("/api/variations/{variation_id}")
async def delete_artist_variation(variation_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        row = await db.get_artist_account(database, variation_id)
        if not row:
            raise HTTPException(404, "Variation not found")
        await _verify_artist_ownership(row["artist_id"], user)
        await db.delete_artist_account(database, variation_id)
        return {"ok": True}
    finally:
        await database.close()


# --- Clips ---

@app.get("/api/artists/{artist_id}/clips")
async def list_artist_clips(artist_id: int, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        clips = await db.get_clips(database, artist_id)
        return rows_to_list(clips)
    finally:
        await database.close()


@app.post("/api/artists/{artist_id}/clips/upload")
async def upload_clip(
    artist_id: int,
    file: UploadFile = File(...),
    caption: str = Form(""),
    user: dict = Depends(get_current_user),
):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        directory = _artist_upload_dir(artist)
        # Insert first to get clip id, then save file with that id
        filename = Path(file.filename or "clip.mp4").name
        clip_id = await db.create_clip(
            database, artist_id=artist_id, source="upload", filename=filename, caption=caption or None,
        )
        ext = Path(filename).suffix.lower() or ".mp4"
        dest = directory / f"{clip_id}{ext}"
        content = await file.read()
        dest.write_bytes(content)
        await db.update_clip(database, clip_id, local_path=str(dest))
        try:
            await clip_scheduler.maybe_resume_on_new_clip(database, artist_id)
        except Exception:
            pass
        clip = await db.get_clip(database, clip_id)
        return row_to_dict(clip)
    finally:
        await database.close()


@app.post("/api/artists/{artist_id}/clips/gdrive")
async def sync_gdrive_clips(artist_id: int, data: GdriveSyncReq, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    folder_id = gdrive_svc.parse_folder_id(data.folder_url)
    if not folder_id:
        raise HTTPException(400, "Couldn't parse a Drive folder id from that URL")

    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
        api_key = cfg.get("oauth_google_drive_api_key") or await db.get_setting(database, "google_api_key")
        if not api_key:
            raise HTTPException(400, "Google Drive API key not configured — set it in Admin → OAuth Apps")
        try:
            files = await gdrive_svc.list_video_files(folder_id, api_key)
        except gdrive_svc.GDriveError as e:
            raise HTTPException(400, str(e))

        # Upsert: existing clips with gdrive_file_id keep their captions, new files added.
        existing = await db.get_clips(database, artist_id)
        existing_by_id = {c.get("gdrive_file_id"): c for c in existing if c.get("gdrive_file_id")}

        added = 0
        for f in files:
            fid = f.get("id")
            if not fid or fid in existing_by_id:
                continue
            await db.create_clip(
                database, artist_id=artist_id, source="gdrive",
                filename=f.get("name", "clip.mp4"), gdrive_file_id=fid,
            )
            added += 1

        # Persist folder URL/id on the artist for reuse
        await db.update_artist(
            database, artist_id, gdrive_folder_url=data.folder_url, gdrive_folder_id=folder_id
        )

        if added:
            try:
                await clip_scheduler.maybe_resume_on_new_clip(database, artist_id)
            except Exception as _resume_exc:
                # Surface in error_logs so an unpause failure stops being
                # silent. The sync still succeeds; admin can manually unpause
                # if this fires.
                import traceback as _tb_local
                try:
                    await db.log_error(
                        database,
                        source="scheduler.maybe_resume_on_new_clip",
                        message=str(_resume_exc),
                        traceback=_tb_local.format_exc(),
                        context=f"artist_id={artist_id} added={added}",
                    )
                except Exception:
                    pass
        clips = await db.get_clips(database, artist_id)
        return {"added": added, "total": len(clips), "clips": rows_to_list(clips)}
    finally:
        await database.close()


@app.post("/api/variations/{variation_id}/clips/upload")
async def upload_variation_clip(
    variation_id: int,
    file: UploadFile = File(...),
    caption: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """Variation-scoped manual upload — clip is only postable by this variation."""
    database = await db.get_db()
    try:
        var = await db.get_artist_account(database, variation_id)
        if not var:
            raise HTTPException(404, "Variation not found")
        artist = await _verify_artist_ownership(var["artist_id"], user)
        directory = _artist_upload_dir(artist) / f"v{variation_id}"
        directory.mkdir(parents=True, exist_ok=True)
        filename = Path(file.filename or "clip.mp4").name
        clip_id = await db.create_clip(
            database, artist_id=var["artist_id"], source="upload",
            filename=filename, caption=caption or None,
            artist_account_id=variation_id,
        )
        ext = Path(filename).suffix.lower() or ".mp4"
        dest = directory / f"{clip_id}{ext}"
        content = await file.read()
        dest.write_bytes(content)
        await db.update_clip(database, clip_id, local_path=str(dest))
        try:
            await clip_scheduler.maybe_resume_on_new_clip(
                database, var["artist_id"], variation_id
            )
        except Exception:
            pass
        clip = await db.get_clip(database, clip_id)
        return row_to_dict(clip)
    finally:
        await database.close()


@app.post("/api/variations/{variation_id}/clips/gdrive")
async def sync_variation_gdrive_clips(
    variation_id: int, data: GdriveSyncReq, user: dict = Depends(get_current_user)
):
    """Sync a Drive folder into one variation's clip pool.

    Mirrors `/api/artists/{id}/clips/gdrive` but tags every new clip with
    `artist_account_id=variation_id` so only that variation will pick it up.
    The shared-pool endpoint is still available for clips usable by every
    variation."""
    database = await db.get_db()
    try:
        var = await db.get_artist_account(database, variation_id)
        if not var:
            raise HTTPException(404, "Variation not found")
        await _verify_artist_ownership(var["artist_id"], user)
        folder_id = gdrive_svc.parse_folder_id(data.folder_url)
        if not folder_id:
            raise HTTPException(400, "Couldn't parse a Drive folder id from that URL")

        cfg = await db.get_site_config(database)
        api_key = cfg.get("oauth_google_drive_api_key") or await db.get_setting(database, "google_api_key")
        if not api_key:
            raise HTTPException(400, "Google Drive API key not configured — set it in Admin → OAuth Apps")
        try:
            files = await gdrive_svc.list_video_files(folder_id, api_key)
        except gdrive_svc.GDriveError as e:
            raise HTTPException(400, str(e))

        existing = await db.get_clips(database, var["artist_id"])
        # Dedup on (artist_account_id, gdrive_file_id) — a file present in
        # both the shared pool and this variation's folder stays distinct,
        # but the same file synced twice into THIS variation only counts once.
        existing_by_id = {
            c.get("gdrive_file_id"): c for c in existing
            if c.get("gdrive_file_id") and c.get("artist_account_id") == variation_id
        }

        added = 0
        for f in files:
            fid = f.get("id")
            if not fid or fid in existing_by_id:
                continue
            await db.create_clip(
                database, artist_id=var["artist_id"], source="gdrive",
                filename=f.get("name", "clip.mp4"), gdrive_file_id=fid,
                artist_account_id=variation_id,
            )
            added += 1

        await db.update_artist_account(
            database, variation_id,
            gdrive_folder_url=data.folder_url, gdrive_folder_id=folder_id,
        )

        if added:
            try:
                await clip_scheduler.maybe_resume_on_new_clip(
                    database, var["artist_id"], variation_id
                )
            except Exception as _resume_exc:
                import traceback as _tb_local
                try:
                    await db.log_error(
                        database,
                        source="scheduler.maybe_resume_on_new_clip",
                        message=str(_resume_exc),
                        traceback=_tb_local.format_exc(),
                        context=f"variation_id={variation_id} added={added}",
                    )
                except Exception:
                    pass
        clips = await db.get_clips(database, var["artist_id"])
        var_clips = [c for c in clips if c.get("artist_account_id") == variation_id]
        return {"added": added, "total": len(var_clips), "clips": rows_to_list(var_clips)}
    finally:
        await database.close()


@app.put("/api/clips/{clip_id}")
async def update_clip_route(clip_id: int, data: ClipUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        clip = await db.get_clip(database, clip_id)
        if not clip:
            raise HTTPException(404, "Clip not found")
        await _verify_artist_ownership(clip["artist_id"], user)
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if updates:
            await db.update_clip(database, clip_id, **updates)
        clip = await db.get_clip(database, clip_id)
        return row_to_dict(clip)
    finally:
        await database.close()


@app.delete("/api/clips/{clip_id}")
async def delete_clip_route(clip_id: int, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        clip = await db.get_clip(database, clip_id)
        if not clip:
            raise HTTPException(404, "Clip not found")
        await _verify_artist_ownership(clip["artist_id"], user)
        local = clip.get("local_path")
        await db.delete_clip(database, clip_id)
    finally:
        await database.close()
    if local:
        try:
            Path(local).unlink(missing_ok=True)
        except OSError:
            pass
    # Also drop the per-variation diversified renders for this clip.
    div_dir = Path("uploads/variation_renders") / str(clip_id)
    if div_dir.exists():
        try:
            import shutil as _sh
            _sh.rmtree(div_dir, ignore_errors=True)
        except Exception:
            pass
    return {"ok": True}


# --- Dashboard / feed ---

@app.get("/api/artists/{artist_id}/dashboard")
async def artist_dashboard(artist_id: int, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        variations = await db.get_artist_accounts(database, artist_id)
        clips = await db.get_clips(database, artist_id)
        posts = await db.get_clip_posts(database, artist_id=artist_id)

        # Load artist first so we can compute "today" in the artist's
        # configured timezone. Using UTC midnight here surfaces yesterday's
        # late posts as "today's" on the dashboard whenever the artist
        # window crosses UTC midnight (the common case for US/Eastern).
        artist_row = await db.get_artist(database, artist_id)
        artist_d = dict(artist_row) if artist_row else {}
        try:
            tz = ZoneInfo(artist_d.get("timezone") or "US/Eastern")
        except Exception:
            tz = ZoneInfo("US/Eastern")
        now_utc = datetime.now(timezone.utc)
        today = now_utc.astimezone(tz).date()

        posts_today = 0
        posts_total = 0
        by_platform = {
            p: {"posted": 0, "views": 0}
            for p in ("tiktok", "youtube", "instagram", "facebook")
        }
        next_scheduled_at = None
        # Dedup set: tracks (clip_id_or_row_id, artist_account_id, platform) so
        # stale-slot double-posts never inflate posts_total / posts_today / by_platform.
        # Uses row id as fallback when clip_id is NULL (TikTok phone-discovery rows).
        # posted_as_draft=TRUE rows are excluded — those are TikTok drafts not yet
        # published. The discovery row inserted when user publishes is counted instead.
        _counted_posts: set[tuple] = set()

        for p in posts:
            platform = p.get("platform")
            status = p.get("status")
            if status == "posted":
                # Views accumulate forever — include deleted posts in the view
                # total so counts never drop when a post is removed from the
                # platform. The view_count column is preserved when deleted_at
                # is set (the poller never clears it).
                if platform in by_platform:
                    by_platform[platform]["views"] += int(p.get("view_count") or 0)
                # Post count and "today" count:
                #   - Exclude deleted posts
                #   - Exclude posted_as_draft=TRUE rows — these are TikTok drafts
                #     sitting in Creator Inbox waiting for the user to publish.
                #     The system uploaded them but the video is not yet live.
                #     Once the user publishes from their phone, TikTok discovery
                #     inserts a NULL-clip row with the real video ID, and THAT
                #     row is what we count instead.
                #   - NULL-clip rows (clip_id IS NULL) represent phone-published
                #     videos discovered via TikTok API — count them normally.
                if not p.get("deleted_at") and not p.get("posted_as_draft"):
                    _dedup_key = (
                        p.get("clip_id") if p.get("clip_id") is not None else p.get("id"),
                        p.get("artist_account_id"),
                        platform,
                    )
                    if _dedup_key in _counted_posts:
                        continue
                    _counted_posts.add(_dedup_key)
                    posts_total += 1
                    if platform in by_platform:
                        by_platform[platform]["posted"] += 1
                    posted_at = p.get("posted_at")
                    if isinstance(posted_at, datetime):
                        # DB stores naive UTC; treat as UTC then convert to artist tz.
                        if posted_at.tzinfo is None:
                            posted_at = posted_at.replace(tzinfo=timezone.utc)
                        if posted_at.astimezone(tz).date() == today:
                            posts_today += 1
            elif status == "scheduled":
                sch = p.get("scheduled_for")
                if isinstance(sch, datetime):
                    # Normalise to UTC-aware for comparison.
                    if sch.tzinfo is None:
                        sch = sch.replace(tzinfo=timezone.utc)
                    # Only count FUTURE slots as the "next slot". Past-dated
                    # scheduled rows exist when an artist/variation became paused
                    # after the slot was planned — the dispatcher skips them
                    # (paused_reason IS NULL filter). Surfacing them as "next slot"
                    # shows a stale past date that never advances, misleading the
                    # operator into thinking a post is imminent.
                    if sch > now_utc:
                        if next_scheduled_at is None or sch < next_scheduled_at:
                            next_scheduled_at = sch

        current_cid = artist_d.get("current_campaign_id")
        campaign = None
        if current_cid:
            c = await db.get_campaign(database, current_cid)
            campaign = row_to_dict(c) if c else None

        # View-poller heartbeat for the dashboard countdown. Interval is
        # admin-configurable via site_config.view_poll_interval_seconds.
        from services.clip_scheduler import get_view_poll_interval
        poll_interval = await get_view_poll_interval(database)
        cur = await database.execute(
            "SELECT MAX(view_count_updated_at) AS last_polled_at "
            "FROM clip_posts WHERE artist_id = ? AND status = ?",
            (artist_id, "posted"),
        )
        lp_rows = await cur.fetchall()
        last_polled_at = lp_rows[0]["last_polled_at"] if lp_rows else None
        if last_polled_at is not None:
            if last_polled_at.tzinfo is None:
                last_polled_at = last_polled_at.replace(tzinfo=timezone.utc)
            next_poll_at = last_polled_at + timedelta(seconds=poll_interval)
        else:
            next_poll_at = datetime.now(timezone.utc) + timedelta(seconds=poll_interval)

        # Per-variation: next scheduled slot clip filename (for dashboard UI)
        var_next_clip: dict[int, str | None] = {}
        for var in variations:
            vid = dict(var)["id"]
            nc_cur = await database.execute(
                """
                SELECT c.filename FROM clip_posts cp
                JOIN clips c ON c.id = cp.clip_id
                WHERE cp.artist_account_id = ?
                  AND cp.status = 'scheduled'
                  AND cp.scheduled_for IS NOT NULL
                ORDER BY cp.scheduled_for ASC LIMIT 1
                """,
                (vid,),
            )
            nc_row = await nc_cur.fetchone()
            var_next_clip[vid] = nc_row["filename"] if nc_row else None

        return {
            "variations_count": len(variations),
            "active_clips": len(clips),
            "posts_today": posts_today,
            "posts_total": posts_total,
            "views_total": sum(b["views"] for b in by_platform.values()),
            "by_platform": by_platform,
            "next_scheduled_at": (
                (next_scheduled_at.replace(tzinfo=timezone.utc) if next_scheduled_at.tzinfo is None else next_scheduled_at).isoformat()
                if next_scheduled_at
                else None
            ),
            "is_active": bool(artist_d.get("is_active")),
            "paused_reason": artist_d.get("paused_reason"),
            "view_target": artist_d.get("view_target"),
            "current_campaign": campaign,
            "poll": {
                "interval_seconds": poll_interval,
                "last_polled_at": last_polled_at.isoformat() if last_polled_at else None,
                "next_poll_at": next_poll_at.isoformat(),
            },
            "variation_next_clips": var_next_clip,
        }
    finally:
        await database.close()


@app.get("/api/artists/{artist_id}/feed")
async def artist_feed(artist_id: int, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        posts = await db.get_clip_posts(database, artist_id=artist_id, limit=100)
        return rows_to_list(posts)
    finally:
        await database.close()


def _friendly_error(raw: str | None) -> str:
    """Convert a raw clip_post error string to a user-readable message."""
    if not raw:
        return "Unknown error"
    err = raw.lower()
    if "reached_active_user_cap" in err or "active_user_cap" in err:
        return "TikTok account has reached its active user cap — contact TikTok support"
    if "rate_limit" in err or "rate limit" in err or "spam" in err or "too frequent" in err:
        return "Rate limit hit — try again in a few hours"
    if "token" in err or "oauth" in err or "credentials" in err or "unauthorized" in err or "unauthenticated" in err or "access_token" in err:
        return "Account credentials expired — reconnect the account"
    if "duplicate" in err or "already posted" in err or "already exists" in err:
        return "Video already posted to this platform"
    if "clip or variation missing" in err or "file not found" in err or "no such file" in err:
        return "Content file missing — re-upload the clip"
    if "ig container processing timed out" in err or "ig container couldn't fetch" in err or "could not download video for instagram" in err:
        return "Instagram couldn't fetch the video — retrying will serve it through our server"
    if "ig container error" in err:
        return f"Instagram rejected the video: {raw.split('IG container error:')[-1].strip()[:120]}"
    if "timeout" in err or "timed out" in err:
        return "Request timed out — safe to retry"
    if "privacy" in err:
        return "Invalid privacy setting — check TikTok settings"
    if "size" in err or "too large" in err or "file size" in err:
        return "File size too large for this platform"
    if "network" in err or "connection" in err or "connection error" in err:
        return "Network error — safe to retry"
    if "slot lapsed" in err:
        return "Slot lapsed while artist was paused — will be re-scheduled automatically"
    if "unaudited_client_can_only_post_to_private_accounts" in err:
        return "TikTok app not yet audited — video sent to drafts (open TikTok to publish)"
    if "368" in err or "confirm your identity" in err or "confirm_identity" in err:
        return "Facebook requires identity verification — open the Facebook app and complete the identity check for this Page"
    if "403" in err or "forbidden" in err:
        return "Access denied — account may need to be reconnected"
    if "404" in err or "not found" in err:
        return "Resource not found — content may have been deleted"
    if "500" in err or "server error" in err or "internal" in err:
        return "Platform server error — safe to retry"
    # Strip raw JSON/long errors — just show first clean sentence or 120 chars
    import re as _re
    cleaned = _re.sub(r'\{.*?\}', '', raw, flags=_re.DOTALL).strip(" :{}")
    cleaned = cleaned.split("\n")[0].strip()
    return cleaned[:120] if cleaned else raw[:120]


@app.get("/api/artists/{artist_id}/failed-clip-posts")
async def artist_failed_clip_posts(artist_id: int, user: dict = Depends(get_current_user)):
    """Return failed clip_posts for this artist (last 24 h, limit 50)."""
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        cur = await database.execute(
            """
            SELECT cp.id, cp.platform, cp.error, cp.scheduled_for,
                   cp.clip_id, cp.artist_account_id,
                   aa.tiktok_handle, aa.youtube_handle, aa.instagram_handle,
                   aa.facebook_handle, aa.name AS variation_name
            FROM clip_posts cp
            LEFT JOIN artist_accounts aa ON aa.id = cp.artist_account_id
            WHERE cp.artist_id = ?
              AND cp.status = 'failed'
              AND (cp.scheduled_for IS NULL OR cp.scheduled_for > NOW() - INTERVAL '7 days')
              AND (cp.error IS NULL OR (cp.error NOT LIKE '%Slot lapsed%' AND cp.error NOT LIKE '%Stale slot replaced%'))
            ORDER BY cp.id DESC
            LIMIT 50
            """,
            (artist_id,),
        )
        rows = await cur.fetchall()
        result = []
        for r in rows:
            rd = dict(r)
            # Build a human-readable variation name from handles
            handles = []
            for plat in ("tiktok", "youtube", "instagram", "facebook"):
                h = rd.get(f"{plat}_handle")
                if h:
                    handles.append(f"@{h.lstrip('@')}")
            variation_label = rd.get("variation_name") or (handles[0] if handles else f"Variation #{rd['artist_account_id']}")
            result.append({
                "id": rd["id"],
                "platform": rd["platform"],
                "variation_name": variation_label,
                "error": rd.get("error"),
                "friendly_error": _friendly_error(rd.get("error")),
                "scheduled_for": rd["scheduled_for"].isoformat() if rd.get("scheduled_for") else None,
            })
        return result
    finally:
        await database.close()


@app.delete("/api/artists/{artist_id}/failed-clip-posts")
async def clear_failed_clip_posts(artist_id: int, user: dict = Depends(get_current_user)):
    """Delete all failed clip_posts for this artist."""
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        await database.execute(
            """
            DELETE FROM clip_posts
            WHERE artist_id = ?
              AND status = 'failed'
            """,
            (artist_id,),
        )
        await database.commit()
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/clip-posts/{clip_post_id}/retry")
async def retry_clip_post(
    clip_post_id: int,
    mode: str = Query("normal", description="'normal' (apply cap cooldown) or 'draft' (post immediately as TikTok inbox draft)"),
    user: dict = Depends(get_current_user),
):
    """Reset a failed clip_post to scheduled so the dispatcher re-attempts it.

    mode=draft  → sets force_inbox=TRUE + schedules immediately. Dispatcher will
                  use TikTok INBOX mode for this row only, regardless of variation
                  settings. Intended for cap-error TikTok posts.
    mode=normal → existing behaviour: 6h cooldown for cap errors, 2min otherwise.
    """
    database = await db.get_db()
    try:
        # Ownership check: the clip_post's artist must belong to this user
        cur = await database.execute(
            """
            SELECT cp.id, cp.artist_id, cp.status, cp.platform
            FROM clip_posts cp
            JOIN artists a ON a.id = cp.artist_id
            WHERE cp.id = ? AND a.user_id = ?
            """,
            (clip_post_id, user["id"]),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Clip post not found or access denied")
        row_d = dict(row)
        if row_d["status"] != "failed":
            raise HTTPException(400, "Only failed posts can be retried")

        if mode == "draft":
            # Retry immediately as TikTok inbox draft — force_inbox tells the
            # dispatcher to use INBOX mode for this specific row only.
            if row_d.get("platform") != "tiktok":
                raise HTTPException(400, "Draft mode is only available for TikTok posts")
            cur2 = await database.execute(
                "UPDATE clip_posts SET status = 'scheduled', scheduled_for = NOW(), "
                "error = NULL, force_inbox = TRUE WHERE id = ? RETURNING scheduled_for",
                (clip_post_id,),
            )
            ret = await cur2.fetchone()
            await database.commit()
            scheduled_for = dict(ret)["scheduled_for"] if ret else None
            return {"ok": True, "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
                    "cooldown_hours": 0, "mode": "draft"}

        # mode=normal — fetch the error to apply the right cooldown.
        err_cur = await database.execute(
            "SELECT error FROM clip_posts WHERE id = ?", (clip_post_id,)
        )
        err_row = await err_cur.fetchone()
        raw_error = (dict(err_row).get("error") or "") if err_row else ""
        _cooldown_errors = ("reached_active_user_cap", "active_user_cap")
        if any(e in raw_error.lower() for e in _cooldown_errors):
            delay_sql = "NOW() + INTERVAL '6 hours'"
        else:
            delay_sql = "NOW() + INTERVAL '2 minutes'"
        cur2 = await database.execute(
            f"UPDATE clip_posts SET status = 'scheduled', scheduled_for = {delay_sql}, "
            f"error = NULL, force_inbox = FALSE WHERE id = ? RETURNING scheduled_for",
            (clip_post_id,),
        )
        ret = await cur2.fetchone()
        await database.commit()
        scheduled_for = dict(ret)["scheduled_for"] if ret else None
        cooldown_hours = 6 if any(e in raw_error.lower() for e in _cooldown_errors) else 0
        return {"ok": True, "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
                "cooldown_hours": cooldown_hours, "mode": "normal"}
    finally:
        await database.close()


# --- Promotion lifecycle ---

async def _promotion_preflight(database, artist_id: int) -> list[str]:
    """Return a list of human-readable errors blocking promotion start."""
    errors: list[str] = []

    variations = await db.get_artist_accounts(database, artist_id)
    if not variations:
        errors.append("No variations — add at least one variation with platform connections.")

    any_connected = False
    connected_platforms: set[str] = set()
    for v in variations:
        for p in ("tiktok", "youtube", "instagram", "facebook"):
            if dict(v).get(f"{p}_token"):
                any_connected = True
                connected_platforms.add(p)
    if variations and not any_connected:
        errors.append("No platforms connected — click Connect on at least one variation's TikTok / YouTube / Instagram / Facebook tile.")

    clips = await db.get_clips(database, artist_id)
    if not clips:
        errors.append("Video directory is empty — upload MP4s or sync a Google Drive folder.")

    # OAuth app credentials check — if any platform is in use, its client id/secret must exist.
    cfg = await db.get_site_config(database)
    # Instagram can be served by EITHER the Meta FB-Login app OR the standalone
    # Instagram Login app — accept whichever is configured.
    platform_key = {
        "tiktok":    ["tiktok"],
        "youtube":   ["youtube"],
        "facebook":  ["meta"],
        "instagram": ["meta", "instagram"],
    }
    for p in connected_platforms:
        candidates = platform_key[p]
        if not any(cfg.get(f"oauth_{k}_client_id") and cfg.get(f"oauth_{k}_client_secret") for k in candidates):
            errors.append(f"{p.capitalize()} OAuth app credentials not configured in admin settings.")

    # Google Drive key required if any clip is sourced from Drive.
    has_gdrive = any((dict(c).get("source") == "gdrive") for c in clips)
    if has_gdrive and not cfg.get("oauth_google_drive_api_key"):
        errors.append("Google Drive API key missing — set it in Admin → OAuth Apps.")

    return errors


@app.post("/api/artists/{artist_id}/promotion/start")
async def promotion_start(
    artist_id: int, data: PromotionStartReq, user: dict = Depends(get_current_user)
):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        errors = await _promotion_preflight(database, artist_id)
        if errors:
            raise HTTPException(400, {"errors": errors})

        # Already running? Just return current state.
        current_cid = artist.get("current_campaign_id")
        if artist.get("is_active") and current_cid:
            campaign = await db.get_campaign(database, current_cid)
            return {"ok": True, "campaign": dict(campaign) if campaign else None}

        name = (data.campaign_name or "").strip() or \
            f"Campaign — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
        cid = await db.create_campaign(
            database, artist_id=artist_id, name=name, view_target=data.view_target,
        )
        await db.update_artist(
            database, artist_id,
            is_active=True, paused_reason=None,
            view_target=data.view_target,
            current_campaign_id=cid,
        )
        return {"ok": True, "campaign_id": cid}
    finally:
        await database.close()


@app.post("/api/artists/{artist_id}/promotion/stop")
async def promotion_stop(artist_id: int, user: dict = Depends(get_current_user)):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        await db.update_artist(database, artist_id, is_active=False)
        cid = artist.get("current_campaign_id")
        if cid:
            posts = await db.get_clip_posts(database, artist_id=artist_id)
            views = sum(int(p.get("view_count") or 0) for p in posts if p.get("campaign_id") == cid)
            posts_total = sum(1 for p in posts if p.get("campaign_id") == cid and p.get("status") == "posted")
            await db.update_campaign(
                database, cid, status="ended",
                ended_at=datetime.now(timezone.utc),
                views_total=views, posts_total=posts_total,
            )
        return {"ok": True}
    finally:
        await database.close()


@app.post("/api/artists/{artist_id}/promotion/toggle-pause")
async def promotion_toggle_pause(artist_id: int, user: dict = Depends(get_current_user)):
    """Manual pause/resume toggle. If currently running, pause with reason='manual'.
    If currently paused (for any reason), clear paused_reason and resume.
    No-op when the campaign isn't active (use /promotion/start for that)."""
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        if not artist.get("is_active"):
            return {"ok": True, "is_active": False, "paused_reason": artist.get("paused_reason")}
        from services.clip_scheduler import PAUSE_MANUAL
        new_reason = None if artist.get("paused_reason") else PAUSE_MANUAL
        await db.update_artist(database, artist_id, paused_reason=new_reason)
        return {"ok": True, "is_active": True, "paused_reason": new_reason}
    finally:
        await database.close()


@app.post("/api/artists/{artist_id}/promotion/catchup")
async def promotion_catchup(artist_id: int, user: dict = Depends(get_current_user)):
    """One-shot: plan a now+30s slot for today's missed posts.

    Recovery for the case where the planner first ran late (e.g. after a
    13:00 deploy when the 09:00/11:00 slots were already past). Single
    deliberate user action — does NOT flip `catchup_enabled` on globally.
    """
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        inserted = await clip_scheduler.catchup_today_once(database, artist_id)
        return {"ok": True, "inserted": inserted}
    finally:
        await database.close()


@app.post("/api/artists/{artist_id}/promotion/reset")
async def promotion_reset(
    artist_id: int, data: PromotionResetReq, user: dict = Depends(get_current_user)
):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        # Archive current campaign with a final snapshot.
        cid = artist.get("current_campaign_id")
        if cid:
            posts = await db.get_clip_posts(database, artist_id=artist_id)
            views = sum(int(p.get("view_count") or 0) for p in posts if p.get("campaign_id") == cid)
            posts_total = sum(1 for p in posts if p.get("campaign_id") == cid and p.get("status") == "posted")
            await db.update_campaign(
                database, cid, status="reset",
                ended_at=datetime.now(timezone.utc),
                views_total=views, posts_total=posts_total,
            )

        # Delete clips (and their files), preserve clip_posts for historical CSV.
        clips = await db.get_clips(database, artist_id)
        for c in clips:
            if dict(c).get("source") == "upload" and dict(c).get("local_path"):
                try:
                    Path(dict(c)["local_path"]).unlink(missing_ok=True)
                except Exception:
                    pass
            await db.delete_clip(database, c["id"])

        # Start fresh campaign.
        name = (data.campaign_name or "").strip() or \
            f"Campaign — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
        new_cid = await db.create_campaign(
            database, artist_id=artist_id, name=name, view_target=data.view_target,
        )
        await db.update_artist(
            database, artist_id,
            is_active=False,  # user clicks Start again after re-stocking the directory
            paused_reason=None,
            view_target=data.view_target,
            current_campaign_id=new_cid,
        )
        return {"ok": True, "campaign_id": new_cid}
    finally:
        await database.close()


@app.get("/api/artists/{artist_id}/campaigns")
async def list_campaigns(artist_id: int, user: dict = Depends(get_current_user)):
    await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        rows = await db.get_campaigns(database, artist_id)
        return rows_to_list(rows)
    finally:
        await database.close()


@app.get("/api/artists/{artist_id}/stats.csv")
async def artist_stats_csv(
    artist_id: int,
    campaign_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    artist = await _verify_artist_ownership(artist_id, user)
    database = await db.get_db()
    try:
        posts = await db.get_clip_posts(database, artist_id=artist_id, limit=10000)
        variations = {v["id"]: dict(v) for v in await db.get_artist_accounts(database, artist_id)}
        campaigns = {c["id"]: dict(c) for c in await db.get_campaigns(database, artist_id)}
    finally:
        await database.close()

    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "posted_at", "scheduled_for", "campaign", "platform", "variation",
        "status", "clip", "caption", "platform_post_id", "view_count", "error",
    ])
    for p in posts:
        pd = dict(p)
        if campaign_id is not None and pd.get("campaign_id") != campaign_id:
            continue
        var = variations.get(pd.get("artist_account_id"), {})
        camp = campaigns.get(pd.get("campaign_id"), {})
        w.writerow([
            (pd.get("posted_at").isoformat() if isinstance(pd.get("posted_at"), datetime) else (pd.get("posted_at") or "")),
            (pd.get("scheduled_for").isoformat() if isinstance(pd.get("scheduled_for"), datetime) else (pd.get("scheduled_for") or "")),
            camp.get("name", ""),
            pd.get("platform", ""),
            var.get("name", ""),
            pd.get("status", ""),
            pd.get("clip_filename") or "",
            (pd.get("caption_snapshot") or "").replace("\n", " "),
            pd.get("platform_post_id") or "",
            pd.get("view_count") or 0,
            (pd.get("error") or "").replace("\n", " "),
        ])

    filename = f"{artist['slug']}-stats"
    if campaign_id:
        filename += f"-campaign{campaign_id}"
    filename += ".csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Admin: artists ---

@app.get("/api/admin/artists")
async def admin_list_artists(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        artists = await db.get_artists(database)  # all users
        result = []
        for a in artists:
            variations = await db.get_artist_accounts(database, a["id"])
            clips = await db.get_clips(database, a["id"])
            posts = await db.get_clip_posts(database, artist_id=a["id"])
            owner = await db.get_user(database, a.get("user_id")) if a.get("user_id") else None
            result.append({
                **dict(a),
                "variations_count": len(variations),
                "clips_count": len(clips),
                "posts_count": sum(
                    1 for p in posts
                    if p.get("status") == "posted" and not p.get("deleted_at")
                ),
                "views_total": sum(
                    int(p.get("view_count") or 0) for p in posts
                    if not p.get("deleted_at")
                ),
                "owner_email": dict(owner).get("email") if owner else None,
            })
        return result
    finally:
        await database.close()


@app.delete("/api/admin/artists/{artist_id}")
async def admin_delete_artist(artist_id: int, admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        artist = await db.get_artist(database, artist_id)
        if not artist:
            raise HTTPException(404, "Artist not found")
        await db.delete_artist(database, artist_id)
    finally:
        await database.close()
    upload_dir = Path("uploads") / "artists" / artist["slug"]
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
    return {"ok": True}


# --- Admin: error logs ---

@app.get("/api/admin/error-logs")
async def admin_error_logs(
    limit: int = 200,
    source: Optional[str] = None,
    admin: dict = Depends(admin_required),
):
    database = await db.get_db()
    try:
        rows = await db.get_error_logs(database, limit=min(limit, 1000), source=source)
        return rows_to_list(rows)
    finally:
        await database.close()


@app.delete("/api/admin/error-logs")
async def admin_clear_error_logs(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        await db.delete_old_error_logs(database, keep_last=0)
        return {"ok": True}
    finally:
        await database.close()


# --- Deletion audit ---

@app.post("/api/admin/clip-posts/audit-deleted")
async def admin_audit_deleted(admin: dict = Depends(admin_required)):
    """One-shot audit: re-poll every currently-posted clip_post and let the
    view poller's deletion-detection logic mark rows as deleted_at where the
    platform reports them gone (404 / 'object doesn't exist' / drop-to-zero
    from non-zero). Used to clean up dashboard counts after bulk deletions
    on the platforms.

    Bypasses the staleness gate by clearing view_count_updated_at on every
    live row so the next poll touches all of them.
    """
    database = await db.get_db()
    try:
        await database.execute(
            "UPDATE clip_posts SET view_count_updated_at = NULL "
            "WHERE status = 'posted' AND deleted_at IS NULL"
        )
        await database.commit()
    finally:
        await database.close()
    from services.clip_scheduler import poll_views_once
    await poll_views_once()
    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT COUNT(*) AS n FROM clip_posts WHERE deleted_at IS NOT NULL"
        )
        row = await cur.fetchone()
        deleted_total = int(row["n"]) if row else 0
        cur = await database.execute(
            "SELECT COUNT(*) AS n FROM clip_posts WHERE status = 'posted' AND deleted_at IS NULL"
        )
        row = await cur.fetchone()
        alive_total = int(row["n"]) if row else 0
        return {"ok": True, "alive": alive_total, "deleted": deleted_total}
    finally:
        await database.close()


# --- Cache / retention ---

@app.get("/api/admin/cache-stats")
async def admin_cache_stats(admin: dict = Depends(admin_required)):
    """Sizes + row counts for the two cache layers, so the admin UI can show
    how much is stored before they click Clear."""
    from pathlib import Path as _P
    renders_root = _P("uploads/variation_renders")
    renders_bytes = 0
    renders_count = 0
    renders_oldest: Optional[datetime] = None
    renders_newest: Optional[datetime] = None
    if renders_root.exists():
        for f in renders_root.rglob("*.mp4"):
            try:
                st = f.stat()
            except OSError:
                continue
            renders_count += 1
            renders_bytes += st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if renders_oldest is None or mtime < renders_oldest:
                renders_oldest = mtime
            if renders_newest is None or mtime > renders_newest:
                renders_newest = mtime

    pt_root = _P("uploads/passthrough_clips")
    pt_bytes = 0
    pt_count = 0
    pt_oldest: Optional[datetime] = None
    pt_newest: Optional[datetime] = None
    if pt_root.exists():
        for f in pt_root.rglob("*.mp4"):
            try:
                st = f.stat()
            except OSError:
                continue
            pt_count += 1
            pt_bytes += st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if pt_oldest is None or mtime < pt_oldest:
                pt_oldest = mtime
            if pt_newest is None or mtime > pt_newest:
                pt_newest = mtime

    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT COUNT(*) AS c, MIN(created_at) AS oldest FROM clip_caption_variants"
        )
        row = dict(await cur.fetchone())
        last_diversify_at = (await db.get_site_config(database)).get("last_diversify_at")
    finally:
        await database.close()

    return {
        "video_renders": {
            "count": renders_count,
            "bytes": renders_bytes,
            "oldest": renders_oldest.isoformat() if renders_oldest else None,
            "newest": renders_newest.isoformat() if renders_newest else None,
            # Persisted stamp from the scheduler on each successful diversify.
            # Survives cache cleanup unlike file mtimes.
            "last_run": last_diversify_at,
        },
        "caption_variants": {
            "count": int(row.get("c") or 0),
            "oldest": row.get("oldest").isoformat() if row.get("oldest") else None,
        },
        "passthrough_clips": {
            "count": pt_count,
            "bytes": pt_bytes,
            "oldest": pt_oldest.isoformat() if pt_oldest else None,
            "newest": pt_newest.isoformat() if pt_newest else None,
        },
    }


class CacheClearRequest(BaseModel):
    target: str  # "video_renders" | "caption_variants" | "all"
    older_than_days: Optional[int] = None  # None = clear everything for target


class BrandCacheClearRequest(BaseModel):
    target: str  # "output" | "uploads" | "all"
    # ISO date (YYYY-MM-DD). For "output" this matches the {date} path segment.
    # For "uploads" it's compared against file mtime (no date in the path).
    # None = wipe everything for target.
    older_than_date: Optional[str] = None


@app.post("/api/admin/cache/clear")
async def admin_clear_cache(data: CacheClearRequest, admin: dict = Depends(admin_required)):
    """Clear Phase 1 video renders and/or Phase 2 caption variants.

    * `target`: "video_renders" | "caption_variants" | "all"
    * `older_than_days`: if set, only drop entries older than N days
      (mtime for files, created_at for rows). If None, wipe everything.
    """
    if data.target not in ("video_renders", "caption_variants", "passthrough_clips", "all"):
        raise HTTPException(400, f"Invalid target: {data.target}")

    cutoff: Optional[datetime] = None
    if data.older_than_days is not None:
        if data.older_than_days < 0:
            raise HTTPException(400, "older_than_days must be >= 0")
        cutoff = datetime.now(timezone.utc) - timedelta(days=data.older_than_days)

    out = {
        "video_renders_deleted": 0,
        "caption_variants_deleted": 0,
        "passthrough_clips_deleted": 0,
    }

    if data.target in ("video_renders", "all"):
        from pathlib import Path as _P
        renders_root = _P("uploads/variation_renders")
        if renders_root.exists():
            for f in list(renders_root.rglob("*.mp4")):
                try:
                    st = f.stat()
                except OSError:
                    continue
                if cutoff is not None:
                    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                    if mtime >= cutoff:
                        continue
                try:
                    f.unlink()
                    out["video_renders_deleted"] += 1
                except OSError:
                    pass
            # Prune empty clip-id subdirs
            for d in sorted(renders_root.rglob("*"), key=lambda p: -len(p.parts)):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass

    if data.target in ("passthrough_clips", "all"):
        # Per-clip raw-source cache used when diversification is off (so
        # TikTok still gets a verified-domain URL). Cleared with the same
        # rules — older-than cutoff applies, otherwise wipe the dir.
        from pathlib import Path as _P
        pt_root = _P("uploads/passthrough_clips")
        if pt_root.exists():
            for f in list(pt_root.rglob("*.mp4")):
                try:
                    st = f.stat()
                except OSError:
                    continue
                if cutoff is not None:
                    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                    if mtime >= cutoff:
                        continue
                try:
                    f.unlink()
                    out["passthrough_clips_deleted"] += 1
                except OSError:
                    pass

    if data.target in ("caption_variants", "all"):
        database = await db.get_db()
        try:
            if cutoff is not None:
                cur = await database.execute(
                    "DELETE FROM clip_caption_variants WHERE created_at < ? RETURNING 1",
                    (cutoff,),
                )
            else:
                cur = await database.execute(
                    "DELETE FROM clip_caption_variants RETURNING 1"
                )
            deleted = await cur.fetchall()
            out["caption_variants_deleted"] = len(deleted)
        finally:
            await database.close()

    return {"ok": True, **out}


# --- Brand post renders / uploads cleanup ---

def _dir_size(p):
    total = 0
    count = 0
    oldest_mtime = None
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    st = f.stat()
                except OSError:
                    continue
                total += st.st_size
                count += 1
                if oldest_mtime is None or st.st_mtime < oldest_mtime:
                    oldest_mtime = st.st_mtime
    except OSError:
        pass
    return total, count, oldest_mtime


@app.get("/api/admin/brand-cache-stats")
async def admin_brand_cache_stats(admin: dict = Depends(admin_required)):
    from pathlib import Path as _P
    out_root = _P("output")
    up_root = _P("uploads")

    out_bytes, out_count, out_oldest = _dir_size(out_root)
    up_bytes, up_count, up_oldest = _dir_size(up_root)

    # Report the oldest `{date}` subfolder for output too — that's what the
    # date-segment filter operates on, so the admin can pick a sensible cutoff.
    oldest_date_seg = None
    if out_root.exists():
        date_dirs: list[str] = []
        for brand_dir in out_root.iterdir():
            if not brand_dir.is_dir():
                continue
            for date_dir in brand_dir.iterdir():
                if date_dir.is_dir() and len(date_dir.name) == 10 and date_dir.name[4] == "-":
                    date_dirs.append(date_dir.name)
        if date_dirs:
            oldest_date_seg = min(date_dirs)

    return {
        "output": {
            "count": out_count,
            "bytes": out_bytes,
            "oldest_mtime": datetime.fromtimestamp(out_oldest, tz=timezone.utc).isoformat() if out_oldest else None,
            "oldest_date_segment": oldest_date_seg,
        },
        "uploads": {
            "count": up_count,
            "bytes": up_bytes,
            "oldest_mtime": datetime.fromtimestamp(up_oldest, tz=timezone.utc).isoformat() if up_oldest else None,
        },
    }


@app.post("/api/admin/brand-cache/clear")
async def admin_clear_brand_cache(data: BrandCacheClearRequest, admin: dict = Depends(admin_required)):
    """Clear brand post renders (`output/`) and/or uploaded slide sources (`uploads/`).

    * `target`: "output" | "uploads" | "all"
    * `older_than_date`: ISO YYYY-MM-DD. For "output" this matches the
      `{date}` path segment (output/{slug}/{date}/...) — the cleanest
      notion of "post older than" for brands. For "uploads" (no date
      in the path) we compare file mtime. None → wipe everything for target.

    DOES NOT touch DB rows. Stale `outputs` table rows will have broken
    paths after a wipe but that's self-healing on regenerate.
    """
    if data.target not in ("output", "uploads", "all"):
        raise HTTPException(400, f"Invalid target: {data.target}")

    cutoff_date = None
    cutoff_mtime = None
    if data.older_than_date:
        try:
            cutoff_date = datetime.strptime(data.older_than_date, "%Y-%m-%d").date()
            cutoff_mtime = datetime.combine(cutoff_date, dtime.min, tzinfo=timezone.utc).timestamp()
        except ValueError:
            raise HTTPException(400, "older_than_date must be YYYY-MM-DD")

    from pathlib import Path as _P
    out = {"output_dirs_deleted": 0, "output_bytes_freed": 0,
           "uploads_files_deleted": 0, "uploads_bytes_freed": 0}

    # --- Output trees: {brand}/{date}/{account}/post_{N}/ ---
    if data.target in ("output", "all"):
        root = _P("output")
        if root.exists():
            for brand_dir in list(root.iterdir()):
                if not brand_dir.is_dir():
                    continue
                for date_dir in list(brand_dir.iterdir()):
                    if not date_dir.is_dir():
                        continue
                    # Only operate on YYYY-MM-DD segments
                    if not (len(date_dir.name) == 10 and date_dir.name[4] == "-" and date_dir.name[7] == "-"):
                        continue
                    if cutoff_date is not None:
                        try:
                            seg = datetime.strptime(date_dir.name, "%Y-%m-%d").date()
                        except ValueError:
                            continue
                        if seg >= cutoff_date:
                            continue
                    sz, _cnt, _ = _dir_size(date_dir)
                    try:
                        shutil.rmtree(date_dir, ignore_errors=True)
                        out["output_dirs_deleted"] += 1
                        out["output_bytes_freed"] += sz
                    except OSError:
                        pass
                # Prune empty brand dirs
                try:
                    brand_dir.rmdir()
                except OSError:
                    pass

    # --- Uploads: {brand}/post_{N}/**/*.(jpg|png) by mtime ---
    if data.target in ("uploads", "all"):
        root = _P("uploads")
        if root.exists():
            for f in list(root.rglob("*")):
                if not f.is_file():
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                if cutoff_mtime is not None and st.st_mtime >= cutoff_mtime:
                    continue
                try:
                    f.unlink()
                    out["uploads_files_deleted"] += 1
                    out["uploads_bytes_freed"] += st.st_size
                except OSError:
                    pass
            # Prune empty subdirs (post_*/variations, post_*, brand dirs)
            for d in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass

    return {"ok": True, **out}


# ---------------------------------------------------------------------------
# Admin: reconcile a clip_post's platform_post_id when the stored id is stale.
# The actual live video on the platform can have a different id than what we
# stored (race-condition leftovers, or the operator deleted the wrong one).
# POSTing here updates platform_post_id and forces the view poller to re-check
# this row immediately.
# ---------------------------------------------------------------------------
@app.post("/api/admin/clip-posts/{clip_post_id}/reconcile")
async def admin_reconcile_clip_post(
    clip_post_id: int,
    payload: dict,
    admin: dict = Depends(admin_required),
):
    new_id = (payload or {}).get("platform_post_id")
    if not new_id or not isinstance(new_id, str):
        raise HTTPException(400, "platform_post_id (string) is required")

    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT id, platform, platform_post_id, view_count FROM clip_posts WHERE id = ?",
            (clip_post_id,),
        )
        rows = await cur.fetchall()
        if not rows:
            raise HTTPException(404, f"clip_post {clip_post_id} not found")
        before = dict(rows[0])
        await db.update_clip_post(
            database, clip_post_id,
            platform_post_id=new_id,
            view_count_updated_at=None,  # make poller pick this up on next tick
        )
        polled = None
        try:
            from services.clip_scheduler import poll_views_once
            await poll_views_once()
            cur = await database.execute(
                "SELECT view_count, view_count_updated_at FROM clip_posts WHERE id = ?",
                (clip_post_id,),
            )
            after = await cur.fetchall()
            if after:
                polled = dict(after[0])
        except Exception as e:  # noqa: BLE001
            polled = {"error": str(e)}
        return {"ok": True, "before": before, "new_platform_post_id": new_id, "polled": polled}
    finally:
        await database.close()


# ---------------------------------------------------------------------------
# Audio to Video endpoints
# ---------------------------------------------------------------------------

class AudioSplitRequest(BaseModel):
    clips: int  # 1, 3, or 5


class AudioGenerateRequest(BaseModel):
    template_id: str = "minimal"
    background_image_path: Optional[str] = None


class AudioLyricsWord(BaseModel):
    word: str
    start_s: float
    end_s: float


class AudioLyricsRequest(BaseModel):
    words: list[AudioLyricsWord]


class AudioAssignRequest(BaseModel):
    artist_account_id: int


@app.get("/api/audio-to-video/tracks")
async def list_audio_tracks(
    artist_id: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """List all audio tracks uploaded for an artist."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT * FROM audio_tracks WHERE artist_id = ? ORDER BY created_at DESC",
            (artist_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await database.close()


@app.post("/api/audio-to-video/upload")
async def upload_audio_track(
    artist_id: int = Form(...),
    title: Optional[str] = Form(None),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload an audio file, transcribe with Whisper, and return word timestamps."""
    allowed = {
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
        "audio/mp4", "audio/m4a", "audio/aac", "audio/x-aac",
        "audio/ogg", "audio/flac",
    }
    content_type = file.content_type or ""
    if content_type not in allowed and not file.filename.lower().endswith(
        (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
    ):
        raise HTTPException(400, "Unsupported audio format")

    # Save uploaded file
    database = await db.get_db()
    try:
        cur = await database.execute("SELECT slug FROM artists WHERE id = ?", (artist_id,))
        artist_row = await cur.fetchone()
        if not artist_row:
            raise HTTPException(404, "Artist not found")
        artist_slug = artist_row["slug"]
    finally:
        await database.close()

    audio_dir = Path("uploads") / artist_slug / "audio_to_video"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename to avoid collisions
    import uuid as _uuid
    safe_name = f"{_uuid.uuid4().hex}_{Path(file.filename).name}"
    audio_path = audio_dir / safe_name
    contents = await file.read()
    audio_path.write_bytes(contents)

    # Get duration via ffprobe
    duration_s: Optional[float] = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        import json as _json
        ffprobe_data = _json.loads(stdout)
        duration_s = float(ffprobe_data.get("format", {}).get("duration", 0)) or None
    except Exception as e:
        print(f"[audio-to-video] ffprobe failed: {e}")

    # Whisper transcription
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        raise HTTPException(500, "OpenAI API key not configured")

    words = []
    try:
        import httpx as _httpx
        with open(str(audio_path), "rb") as audio_f:
            audio_bytes = audio_f.read()

        def _whisper_request():
            with _httpx.Client(timeout=300) as client:
                resp = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    data={
                        "model": "whisper-1",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "word",
                    },
                    files={"file": (safe_name, audio_bytes, "audio/mpeg")},
                )
                if not resp.is_success:
                    raise RuntimeError(f"Whisper API error {resp.status_code}: {resp.text[:200]}")
                return resp.json()

        whisper_result = await asyncio.to_thread(_whisper_request)
        raw_words = whisper_result.get("words") or []
        words = [
            {"word": w["word"].strip(), "start_s": float(w["start"]), "end_s": float(w["end"])}
            for w in raw_words
            if w.get("word", "").strip()
        ]
    except Exception as e:
        print(f"[audio-to-video] Whisper transcription failed: {e}")
        # Continue without words — user can edit manually

    # Save to DB
    database = await db.get_db()
    try:
        cur = await database.execute(
            "INSERT INTO audio_tracks (artist_id, title, local_path, duration_s) VALUES (?, ?, ?, ?)",
            (artist_id, title or Path(file.filename).stem, str(audio_path), duration_s),
        )
        await database.commit()
        track_id = cur.lastrowid

        for w in words:
            await database.execute(
                "INSERT INTO audio_words (audio_track_id, clip_index, word, start_s, end_s) VALUES (?, 0, ?, ?, ?)",
                (track_id, w["word"], w["start_s"], w["end_s"]),
            )
        await database.commit()

        return {
            "track_id": track_id,
            "duration_s": duration_s,
            "words": words,
            "word_count": len(words),
        }
    finally:
        await database.close()


@app.get("/api/audio-to-video/{track_id}")
async def get_audio_track(
    track_id: int,
    user: dict = Depends(get_current_user),
):
    """Get an audio track with its clips and transcription words."""
    database = await db.get_db()
    try:
        cur = await database.execute("SELECT * FROM audio_tracks WHERE id = ?", (track_id,))
        track = await cur.fetchone()
        if not track:
            raise HTTPException(404, "Audio track not found")

        cur = await database.execute(
            "SELECT * FROM audio_clips WHERE audio_track_id = ? ORDER BY clip_index",
            (track_id,),
        )
        clips_rows = await cur.fetchall()

        clips = []
        for c in clips_rows:
            c_dict = dict(c)
            # attach video status
            cur2 = await database.execute(
                "SELECT * FROM audio_video_clips WHERE audio_clip_id = ? ORDER BY id DESC LIMIT 1",
                (c_dict["id"],),
            )
            avc = await cur2.fetchone()
            c_dict["video"] = dict(avc) if avc else None
            clips.append(c_dict)

        cur = await database.execute(
            "SELECT * FROM audio_words WHERE audio_track_id = ? ORDER BY start_s",
            (track_id,),
        )
        words = [dict(w) for w in await cur.fetchall()]

        return {**dict(track), "clips": clips, "words": words}
    finally:
        await database.close()


@app.post("/api/audio-to-video/{track_id}/split")
async def split_audio_track(
    track_id: int,
    data: AudioSplitRequest,
    user: dict = Depends(get_current_user),
):
    """Split an audio track into 1, 3, or 5 equal clips and write FFmpeg segments."""
    if data.clips not in (1, 3, 5):
        raise HTTPException(400, "clips must be 1, 3, or 5")

    database = await db.get_db()
    try:
        cur = await database.execute("SELECT * FROM audio_tracks WHERE id = ?", (track_id,))
        track = await cur.fetchone()
        if not track:
            raise HTTPException(404, "Audio track not found")
        track = dict(track)
    finally:
        await database.close()

    duration = track.get("duration_s") or 0
    if duration <= 0:
        raise HTTPException(400, "Track duration is unknown — cannot split")

    audio_path = track["local_path"]
    clip_dir = Path(audio_path).parent / f"clips_{track_id}"
    clip_dir.mkdir(parents=True, exist_ok=True)

    clip_duration = duration / data.clips
    created_clips = []

    # Delete existing clips for this track
    database = await db.get_db()
    try:
        await database.execute(
            "DELETE FROM audio_clips WHERE audio_track_id = ?", (track_id,)
        )
        await database.commit()
    finally:
        await database.close()

    for i in range(data.clips):
        start_s = i * clip_duration
        end_s = min((i + 1) * clip_duration, duration)
        clip_path = str(clip_dir / f"clip_{i:02d}.mp3")

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", audio_path,
            "-ss", str(start_s),
            "-to", str(end_s),
            "-c", "copy",
            clip_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            raise HTTPException(500, f"FFmpeg split failed for clip {i}: {stderr.decode()[:200]}")

        database = await db.get_db()
        try:
            cur = await database.execute(
                "INSERT INTO audio_clips (audio_track_id, clip_index, start_s, end_s, local_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (track_id, i, start_s, end_s, clip_path),
            )
            await database.commit()
            clip_id = cur.lastrowid
        finally:
            await database.close()

        # Assign words to clip
        database = await db.get_db()
        try:
            await database.execute(
                "UPDATE audio_words SET clip_index = ? "
                "WHERE audio_track_id = ? AND start_s >= ? AND start_s < ?",
                (i, track_id, start_s, end_s),
            )
            await database.commit()

            cur = await database.execute(
                "SELECT COUNT(*) as cnt FROM audio_words WHERE audio_track_id = ? AND clip_index = ?",
                (track_id, i),
            )
            word_count_row = await cur.fetchone()
            word_count = word_count_row["cnt"] if word_count_row else 0
        finally:
            await database.close()

        created_clips.append({
            "clip_id": clip_id,
            "clip_index": i,
            "start_s": start_s,
            "end_s": end_s,
            "word_count": word_count,
        })

    return {"track_id": track_id, "clips": created_clips}


@app.get("/api/audio-to-video/clips/{clip_id}")
async def get_audio_clip(
    clip_id: int,
    user: dict = Depends(get_current_user),
):
    """Get a single audio clip with its words and current video status."""
    database = await db.get_db()
    try:
        cur = await database.execute("SELECT * FROM audio_clips WHERE id = ?", (clip_id,))
        clip = await cur.fetchone()
        if not clip:
            raise HTTPException(404, "Clip not found")
        clip = dict(clip)

        cur = await database.execute(
            "SELECT * FROM audio_words WHERE audio_track_id = ? AND clip_index = ? ORDER BY start_s",
            (clip["audio_track_id"], clip["clip_index"]),
        )
        words = [dict(w) for w in await cur.fetchall()]

        cur = await database.execute(
            "SELECT * FROM audio_video_clips WHERE audio_clip_id = ? ORDER BY id DESC LIMIT 1",
            (clip_id,),
        )
        avc = await cur.fetchone()

        return {**clip, "words": words, "video": dict(avc) if avc else None}
    finally:
        await database.close()


@app.post("/api/audio-to-video/clips/{clip_id}/generate")
async def generate_audio_video_clip(
    clip_id: int,
    data: AudioGenerateRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Kick off async video generation for an audio clip."""
    database = await db.get_db()
    try:
        cur = await database.execute("SELECT * FROM audio_clips WHERE id = ?", (clip_id,))
        clip = await cur.fetchone()
        if not clip:
            raise HTTPException(404, "Clip not found")
        clip = dict(clip)

        # Get words for this clip
        cur = await database.execute(
            "SELECT word, start_s, end_s FROM audio_words "
            "WHERE audio_track_id = ? AND clip_index = ? ORDER BY start_s",
            (clip["audio_track_id"], clip["clip_index"]),
        )
        words = [dict(w) for w in await cur.fetchall()]

        # Get artist slug from audio_tracks
        cur = await database.execute(
            "SELECT at.*, ar.slug FROM audio_tracks at "
            "JOIN artists ar ON ar.id = at.artist_id "
            "WHERE at.id = ?",
            (clip["audio_track_id"],),
        )
        track = await cur.fetchone()
        if not track:
            raise HTTPException(404, "Audio track not found")
        track = dict(track)

        # Create or reset the AudioVideoClip row
        cur = await database.execute(
            "SELECT id FROM audio_video_clips WHERE audio_clip_id = ?", (clip_id,)
        )
        existing = await cur.fetchone()
        if existing:
            await database.execute(
                "UPDATE audio_video_clips SET status = 'generating', error = NULL, "
                "template_id = ?, background_image_path = ?, video_path = NULL WHERE audio_clip_id = ?",
                (data.template_id, data.background_image_path, clip_id),
            )
            await database.commit()
            avc_id = existing["id"]
        else:
            cur = await database.execute(
                "INSERT INTO audio_video_clips (audio_clip_id, template_id, background_image_path, status) "
                "VALUES (?, ?, ?, 'generating')",
                (clip_id, data.template_id, data.background_image_path),
            )
            await database.commit()
            avc_id = cur.lastrowid
    finally:
        await database.close()

    # Output path
    artist_slug = track["slug"]
    out_dir = Path("output") / artist_slug / "audio_clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = str(out_dir / f"clip_{clip_id}.mp4")

    async def _run_generate():
        err = None
        try:
            await audio_video_svc.generate_audio_video_clip(
                audio_clip_path=clip["local_path"],
                clip_start_s=clip["start_s"],
                clip_end_s=clip["end_s"],
                words=words,
                template_id=data.template_id,
                output_path=video_path,
                background_image_path=data.background_image_path,
            )
        except Exception as e:
            err = str(e)
            print(f"[audio-to-video] generate failed clip {clip_id}: {e}")

        database2 = await db.get_db()
        try:
            if err:
                await database2.execute(
                    "UPDATE audio_video_clips SET status = 'failed', error = ? WHERE id = ?",
                    (err[:500], avc_id),
                )
            else:
                await database2.execute(
                    "UPDATE audio_video_clips SET status = 'done', video_path = ? WHERE id = ?",
                    (video_path, avc_id),
                )
            await database2.commit()
        finally:
            await database2.close()

    background_tasks.add_task(_run_generate)
    return {"avc_id": avc_id, "status": "generating"}


@app.put("/api/audio-to-video/clips/{clip_id}/lyrics")
async def update_audio_clip_lyrics(
    clip_id: int,
    data: AudioLyricsRequest,
    user: dict = Depends(get_current_user),
):
    """Update per-word timestamps for a clip; invalidates any generated video."""
    database = await db.get_db()
    try:
        cur = await database.execute("SELECT * FROM audio_clips WHERE id = ?", (clip_id,))
        clip = await cur.fetchone()
        if not clip:
            raise HTTPException(404, "Clip not found")
        clip = dict(clip)

        # Delete existing words for this clip and replace
        await database.execute(
            "DELETE FROM audio_words WHERE audio_track_id = ? AND clip_index = ?",
            (clip["audio_track_id"], clip["clip_index"]),
        )
        for w in data.words:
            await database.execute(
                "INSERT INTO audio_words (audio_track_id, clip_index, word, start_s, end_s) VALUES (?, ?, ?, ?, ?)",
                (clip["audio_track_id"], clip["clip_index"], w.word, w.start_s, w.end_s),
            )
        await database.commit()

        # Invalidate generated video → set back to pending
        await database.execute(
            "UPDATE audio_video_clips SET status = 'pending', video_path = NULL, error = NULL "
            "WHERE audio_clip_id = ?",
            (clip_id,),
        )
        await database.commit()

        return {"ok": True, "word_count": len(data.words)}
    finally:
        await database.close()


@app.post("/api/audio-to-video/clips/{clip_id}/assign")
async def assign_audio_clip(
    clip_id: int,
    data: AudioAssignRequest,
    user: dict = Depends(get_current_user),
):
    """Assign a generated video clip to an artist variation for scheduling."""
    database = await db.get_db()
    try:
        # Verify the clip exists and has a generated video
        cur = await database.execute(
            "SELECT avc.*, ac.audio_track_id, ac.clip_index, ac.start_s, ac.end_s "
            "FROM audio_video_clips avc "
            "JOIN audio_clips ac ON ac.id = avc.audio_clip_id "
            "WHERE avc.audio_clip_id = ? AND avc.status = 'done'",
            (clip_id,),
        )
        avc = await cur.fetchone()
        if not avc:
            raise HTTPException(400, "No completed video for this clip. Generate first.")
        avc = dict(avc)

        # Look up the artist_account to get artist_id
        cur = await database.execute(
            "SELECT * FROM artist_accounts WHERE id = ?", (data.artist_account_id,)
        )
        acct = await cur.fetchone()
        if not acct:
            raise HTTPException(404, "Artist account not found")
        acct = dict(acct)

        # Get clip duration
        clip_duration = avc["end_s"] - avc["start_s"]

        # Create a Clip record that the scheduler can pick up
        video_path = avc["video_path"]
        filename = Path(video_path).name
        clip_db_id = await db.create_clip(
            database,
            artist_id=acct["artist_id"],
            source="audio_to_video",
            filename=filename,
            local_path=video_path,
            duration_s=clip_duration,
            artist_account_id=data.artist_account_id,
        )

        # Update audio_video_clips to record the assignment
        await database.execute(
            "UPDATE audio_video_clips SET artist_account_id = ? WHERE audio_clip_id = ?",
            (data.artist_account_id, clip_id),
        )
        await database.commit()

        return {
            "ok": True,
            "clip_id": clip_db_id,
            "artist_account_id": data.artist_account_id,
        }
    finally:
        await database.close()


@app.delete("/api/audio-to-video/{track_id}")
async def delete_audio_track(
    track_id: int,
    user: dict = Depends(get_current_user),
):
    """Delete an audio track and all its clips/videos."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            "SELECT local_path FROM audio_tracks WHERE id = ?", (track_id,)
        )
        track = await cur.fetchone()
        if not track:
            raise HTTPException(404, "Audio track not found")

        # Cascade-delete via FK; also clean files
        await database.execute("DELETE FROM audio_tracks WHERE id = ?", (track_id,))
        await database.commit()

        # Best-effort file cleanup
        try:
            audio_path = Path(dict(track)["local_path"])
            if audio_path.exists():
                audio_path.unlink()
            # Remove clips dir if it exists
            clips_dir = audio_path.parent / f"clips_{track_id}"
            if clips_dir.exists():
                import shutil as _shutil
                _shutil.rmtree(clips_dir, ignore_errors=True)
        except Exception as e:
            print(f"[audio-to-video] file cleanup failed: {e}")

        return {"ok": True}
    finally:
        await database.close()


# --- Global exception logger ---

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import traceback as _traceback


@app.exception_handler(Exception)
async def _log_unhandled_exception(request: Request, exc: Exception):
    # Don't spam the log with routine 4xx / validation errors.
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    try:
        database = await db.get_db()
        try:
            uid = None
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                try:
                    payload = decode_token(auth.split(" ", 1)[1])
                    uid = payload.get("sub") if isinstance(payload, dict) else None
                    uid = int(uid) if uid else None
                except Exception:
                    uid = None
            await db.log_error(
                database, source="api",
                message=f"{request.method} {request.url.path}: {exc}",
                traceback=_traceback.format_exc(),
                user_id=uid,
            )
        finally:
            await database.close()
    except Exception:
        pass
    raise exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
