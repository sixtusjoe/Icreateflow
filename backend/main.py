"""
ICREATEFLOW API — FastAPI backend for content scaling platform.
"""
import os
import sys
import shutil
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
from services import tiktok_scraper, ocr, generator, overlay, video
from services import flux
from services import oauth as oauth_svc
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
        if dict(user).get("status") == "suspended":
            raise HTTPException(403, "Account suspended")
        return dict(user)
    finally:
        await database.close()


async def admin_required(user: dict = Depends(get_current_user)):
    """Require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


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

class PostImport(BaseModel):
    tiktok_url: str
    brand_id: int
    post_number: int = 1
    caption: Optional[str] = None

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

class PostSchedule(BaseModel):
    scheduled_time: Optional[str] = None
    caption: Optional[str] = None
    music_track_id: Optional[int] = None

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

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows):
    return [dict(r) for r in rows]

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
        user_id = await db.create_user(database, data.email.lower().strip(), pw_hash, data.name.strip())
        user = await db.get_user(database, user_id)
        token = create_access_token(user_id, user["email"], user["role"])
        return {"token": token, "user": user_safe(dict(user))}
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
        scheduled_posts = await _count(
            "SELECT COUNT(*) as count FROM posts WHERE status IN ('scheduled','generating','posting')"
        )
        failed_posts = await _count("SELECT COUNT(*) as count FROM posts WHERE status = 'failed'")
        suspended_users = await _count("SELECT COUNT(*) as count FROM users WHERE status = 'suspended'")

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
            "scheduled_posts": scheduled_posts,
            "failed_posts": failed_posts,
            "suspended_users": suspended_users,
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
        await db.delete_brand(database, brand_id)
        return {"ok": True}
    finally:
        await database.close()


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

OAUTH_PLATFORMS = {"tiktok", "youtube", "meta"}
OAUTH_CONFIG_KEYS = [
    "oauth_tiktok_client_id", "oauth_tiktok_client_secret",
    "oauth_youtube_client_id", "oauth_youtube_client_secret",
    "oauth_meta_client_id", "oauth_meta_client_secret",
    "oauth_google_drive_api_key",
    "oauth_redirect_base",
]


class OAuthAppUpdate(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_key: Optional[str] = None
    redirect_base: Optional[str] = None


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
        result = {"redirect_base": cfg.get("oauth_redirect_base", "")}
        for platform in OAUTH_PLATFORMS:
            cid = cfg.get(f"oauth_{platform}_client_id", "")
            sec = cfg.get(f"oauth_{platform}_client_secret", "")
            result[platform] = {
                "client_id": cid,
                "client_secret_preview": _mask(sec),
                "configured": bool(cid and sec),
            }
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
        return {"ok": True}
    finally:
        await database.close()


# =============================================
# OAUTH CONNECT FLOWS (TikTok / YouTube / Meta)
# =============================================

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


@app.get("/api/oauth/{platform}/start")
async def oauth_start(
    platform: str,
    account_id: Optional[int] = None,
    variation_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    if platform not in oauth_svc.AUTHORIZE_URLS:
        raise HTTPException(400, f"Unknown platform: {platform}")
    if (account_id is None) == (variation_id is None):
        raise HTTPException(400, "Pass exactly one of account_id or variation_id")

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

    client_id = cfg.get(f"oauth_{platform}_client_id", "")
    redirect_base = cfg.get("oauth_redirect_base", "")
    if not client_id or not redirect_base:
        raise HTTPException(400, f"{platform} OAuth app not configured by admin")

    redirect_uri = oauth_svc.build_redirect_uri(redirect_base, platform)
    state = oauth_svc.sign_state(user["id"], target_id, platform, kind=kind)
    auth_url = oauth_svc.build_authorize_url(platform, client_id, redirect_uri, state)
    return {"authorize_url": auth_url}


@app.get("/api/oauth/{platform}/callback")
async def oauth_callback(platform: str, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(_oauth_close_html(False, f"Provider error: {error}"))
    if platform not in oauth_svc.AUTHORIZE_URLS:
        return HTMLResponse(_oauth_close_html(False, "Unknown platform"))
    if not code or not state:
        return HTMLResponse(_oauth_close_html(False, "Missing code or state"))

    verified = oauth_svc.verify_state(state)
    if not verified or verified["platform"] != platform:
        return HTMLResponse(_oauth_close_html(False, "Invalid or expired state"))

    target_id = verified["account_id"]
    kind = verified.get("kind", "account")

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
            return HTMLResponse(_oauth_close_html(False, f"Token exchange failed: {e}"))

        if not tokens.get("access_token"):
            return HTMLResponse(_oauth_close_html(False, "Provider returned no access token"))

        expires_at = None
        if tokens.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tokens["expires_in"]))
            expires_at = expires_at.isoformat()

        # Meta flow populates BOTH instagram_ and facebook_ columns
        target_platforms = ["instagram", "facebook"] if platform == "meta" else [platform]
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

        if kind == "variation":
            await db.update_artist_account(database, target_id, **updates)
        else:
            await db.update_account(database, target_id, **updates)
        return HTMLResponse(_oauth_close_html(True))
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
        brand_id = await db.create_brand(
            database, data.name, data.slug,
            data.background_color, data.timezone, data.default_post_times,
            user_id=user["id"]
        )
        brand = await db.get_brand(database, brand_id)
        return row_to_dict(brand)
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
        await db.delete_brand(database, brand_id)
        return {"ok": True}
    finally:
        await database.close()


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


# =============================================
# POST ROUTES (user-scoped via brand)
# =============================================

@app.get("/api/posts")
async def list_posts(brand_id: Optional[int] = None, date: Optional[str] = None, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        posts = await db.get_posts(database, brand_id=brand_id, date=date, user_id=user["id"])
        result = []
        for p in posts:
            post_dict = dict(p)
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
                for d in output_dir.rglob(f"post_{post['post_number']}"):
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

        post_id = await db.create_post(
            database, data.brand_id,
            datetime.now().strftime("%Y-%m-%d"),
            data.post_number,
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
    post_number: int = Form(1),
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

        post_id = await db.create_post(
            database, brand_id,
            datetime.now().strftime("%Y-%m-%d"),
            post_number,
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
        api_key = await db.get_setting(database, "anthropic_api_key")
        if not api_key:
            api_key = await db.get_setting(database, "claude_api_key")
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

        out_dir = Path("output") / brand["slug"] / post["date"] / account["name"] / f"post_{post['post_number']}"
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

        # Use overlay engine directly with custom text blocks
        from PIL import Image
        font_weight = data.font_weight or overlay.DEFAULT_WEIGHT
        text_style = data.text_style or "stroke"

        img = Image.open(source_image).convert("RGB")
        img_3x4 = overlay.resize_to_3x4(img)

        if custom_texts:
            img_3x4 = overlay._apply_text_block(
                img_3x4, custom_texts,
                weight=font_weight, text_style=text_style,
            )

        output_3x4 = Path(output_path)
        output_3x4.parent.mkdir(parents=True, exist_ok=True)
        img_3x4.save(str(output_3x4), "PNG")

        img_9x16 = overlay.convert_3x4_to_9x16(img_3x4, bg_color)
        output_9x16 = output_3x4.parent / f"{output_3x4.stem}_9x16{output_3x4.suffix}"
        img_9x16.save(str(output_9x16), "PNG")

        return {
            "slide_3x4": str(output_3x4),
            "slide_9x16": str(output_9x16),
            "slide_number": data.slide_number,
            "account_id": data.account_id,
        }
    finally:
        await database.close()


class RegenerateVideo(BaseModel):
    account_id: int


@app.post("/api/posts/{post_id}/regenerate-video")
async def regenerate_single_video(post_id: int, data: RegenerateVideo, user: dict = Depends(get_current_user)):
    """Rebuild the video for a specific account from the current 9:16 slide files."""
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

        # Music path (optional)
        music_path = None
        if post["music_track_id"]:
            c = await database.execute("SELECT file_path FROM music_tracks WHERE id = ?", (post["music_track_id"],))
            t = await c.fetchone()
            if t:
                music_path = t["file_path"]

        out_dir = Path("output") / brand["slug"] / post["date"] / account["name"] / f"post_{post['post_number']}"
        slides_dir = out_dir / "slides"
        if not slides_dir.exists():
            raise HTTPException(400, "No slides directory found — generate the post first")

        # Collect 9:16 slide files in order
        slide_paths = []
        for f in sorted(slides_dir.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg") and "_9x16" in f.stem:
                slide_paths.append(str(f))

        if len(slide_paths) < 2:
            raise HTTPException(400, f"Need at least 2 slides to build a video (found {len(slide_paths)})")

        video_path = str(out_dir / "video.mp4")
        video.build_video(
            slide_paths=slide_paths,
            output_path=video_path,
            music_path=music_path,
        )

        # Update output record
        c = await database.execute(
            "SELECT id FROM outputs WHERE post_id = ? AND account_id = ?", (post_id, data.account_id)
        )
        existing = await c.fetchone()
        if existing:
            await db.update_output(database, existing["id"], video_path=video_path)

        return {"video_path": video_path, "account_id": data.account_id, "slide_count": len(slide_paths)}
    finally:
        await database.close()


# =============================================
# VARIATION ROUTES
# =============================================

@app.put("/api/variations/{variation_id}")
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

        api_token = await db.get_setting(database, "replicate_api_token")

        await flux.generate_image(
            prompt=data.prompt,
            output_path=str(save_path),
            aspect_ratio=data.aspect_ratio,
            api_token=api_token,
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
async def list_music(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        tracks = await db.get_music_tracks(database, user_id=user["id"])
        return rows_to_list(tracks)
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

        zip_path = str(base_dir) + f"_post_{post['post_number']}.zip"
        shutil.make_archive(zip_path.replace(".zip", ""), "zip", str(base_dir))

        return FileResponse(zip_path, filename=Path(zip_path).name, media_type="application/zip")
    finally:
        await database.close()


# =============================================
# FILE SERVING (public — files are behind auth-gated paths anyway)
# =============================================

@app.get("/api/files/{file_path:path}")
async def serve_file(file_path: str):
    full_path = Path(file_path)
    if not full_path.exists():
        for base in [Path("uploads"), Path("output"), Path("music")]:
            candidate = base / file_path
            if candidate.exists():
                full_path = candidate
                break
    if not full_path.exists():
        raise HTTPException(404, "File not found")
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

@app.get("/api/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
        cursor = await database.execute("SELECT * FROM settings")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        await database.close()

@app.put("/api/settings")
async def update_settings(data: SettingUpdate, user: dict = Depends(get_current_user)):
    database = await db.get_db()
    try:
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
        if user["role"] == "admin":
            brands = await database.execute("SELECT COUNT(*) as count FROM brands")
            posts_today = await database.execute(
                "SELECT COUNT(*) as count FROM posts WHERE date = ?",
                (datetime.now().strftime("%Y-%m-%d"),)
            )
            scheduled = await database.execute(
                "SELECT COUNT(*) as count FROM posts WHERE status = 'scheduled'"
            )
            total_posts = await database.execute("SELECT COUNT(*) as count FROM posts")
            accounts = await database.execute("SELECT COUNT(*) as count FROM accounts")
        else:
            brands = await database.execute(
                "SELECT COUNT(*) as count FROM brands WHERE user_id = ?", (user["id"],)
            )
            posts_today = await database.execute(
                "SELECT COUNT(*) as count FROM posts p JOIN brands b ON p.brand_id = b.id WHERE p.date = ? AND b.user_id = ?",
                (datetime.now().strftime("%Y-%m-%d"), user["id"])
            )
            scheduled = await database.execute(
                "SELECT COUNT(*) as count FROM posts p JOIN brands b ON p.brand_id = b.id WHERE p.status = 'scheduled' AND b.user_id = ?",
                (user["id"],)
            )
            total_posts = await database.execute(
                "SELECT COUNT(*) as count FROM posts p JOIN brands b ON p.brand_id = b.id WHERE b.user_id = ?",
                (user["id"],)
            )
            accounts = await database.execute(
                "SELECT COUNT(*) as count FROM accounts a JOIN brands b ON a.brand_id = b.id WHERE b.user_id = ?",
                (user["id"],)
            )

        return {
            "brands": (await brands.fetchone())["count"],
            "accounts": (await accounts.fetchone())["count"],
            "posts_today": (await posts_today.fetchone())["count"],
            "scheduled": (await scheduled.fetchone())["count"],
            "total_posts": (await total_posts.fetchone())["count"],
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
            views_total = sum(int(p.get("view_count") or 0) for p in posts)
            posts_total = sum(1 for p in posts if p.get("status") == "posted")
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
        if updates:
            await db.update_artist_account(database, variation_id, **updates)
        row = await db.get_artist_account(database, variation_id)
        return _artist_account_dict(row)
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
            except Exception:
                pass
        clips = await db.get_clips(database, artist_id)
        return {"added": added, "total": len(clips), "clips": rows_to_list(clips)}
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

        today = datetime.now(timezone.utc).date().isoformat()
        posts_today = 0
        posts_total = 0
        by_platform = {
            p: {"posted": 0, "views": 0}
            for p in ("tiktok", "youtube", "instagram", "facebook")
        }
        next_scheduled_at = None

        for p in posts:
            platform = p.get("platform")
            status = p.get("status")
            if status == "posted":
                posts_total += 1
                if platform in by_platform:
                    by_platform[platform]["posted"] += 1
                    by_platform[platform]["views"] += int(p.get("view_count") or 0)
                posted_at = p.get("posted_at")
                if isinstance(posted_at, datetime) and posted_at.date().isoformat() == today:
                    posts_today += 1
            elif status == "scheduled":
                sch = p.get("scheduled_for")
                if isinstance(sch, datetime):
                    if next_scheduled_at is None or sch < next_scheduled_at:
                        next_scheduled_at = sch

        artist_row = await db.get_artist(database, artist_id)
        artist_d = dict(artist_row) if artist_row else {}
        current_cid = artist_d.get("current_campaign_id")
        campaign = None
        if current_cid:
            c = await db.get_campaign(database, current_cid)
            campaign = dict(c) if c else None

        return {
            "variations_count": len(variations),
            "active_clips": len(clips),
            "posts_today": posts_today,
            "posts_total": posts_total,
            "views_total": sum(b["views"] for b in by_platform.values()),
            "by_platform": by_platform,
            "next_scheduled_at": next_scheduled_at.isoformat() if next_scheduled_at else None,
            "is_active": bool(artist_d.get("is_active")),
            "paused_reason": artist_d.get("paused_reason"),
            "view_target": artist_d.get("view_target"),
            "current_campaign": campaign,
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
    platform_key = {"tiktok": "tiktok", "youtube": "youtube", "instagram": "meta", "facebook": "meta"}
    for p in connected_platforms:
        k = platform_key[p]
        if not (cfg.get(f"oauth_{k}_client_id") and cfg.get(f"oauth_{k}_client_secret")):
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
                "posts_count": sum(1 for p in posts if p.get("status") == "posted"),
                "views_total": sum(int(p.get("view_count") or 0) for p in posts),
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
