"""
ICREATE API — FastAPI backend for content scaling platform.
"""
import os
import sys
import shutil
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
from services import tiktok_scraper, ocr, generator, overlay, video
from services import flux
from services.auth import hash_password, verify_password, create_access_token, decode_token

# --- App setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    Path("uploads").mkdir(exist_ok=True)
    Path("output").mkdir(exist_ok=True)
    Path("music").mkdir(exist_ok=True)
    yield

app = FastAPI(title="ICREATE API", lifespan=lifespan)

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
        if user["role"] != "admin" and brand["user_id"] != user["id"]:
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


@app.get("/api/admin/stats")
async def admin_stats(admin: dict = Depends(admin_required)):
    database = await db.get_db()
    try:
        users_c = await database.execute("SELECT COUNT(*) as count FROM users")
        brands_c = await database.execute("SELECT COUNT(*) as count FROM brands")
        posts_c = await database.execute("SELECT COUNT(*) as count FROM posts")
        tracks_c = await database.execute("SELECT COUNT(*) as count FROM music_tracks")
        return {
            "total_users": (await users_c.fetchone())["count"],
            "total_brands": (await brands_c.fetchone())["count"],
            "total_posts": (await posts_c.fetchone())["count"],
            "total_tracks": (await tracks_c.fetchone())["count"],
        }
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
        if user["role"] == "admin":
            brands = await db.get_brands(database)
        else:
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
        if user["role"] == "admin":
            posts = await db.get_posts(database, brand_id=brand_id, date=date)
        else:
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

        post_id = await db.create_post(
            database, data.brand_id,
            datetime.now().strftime("%Y-%m-%d"),
            data.post_number,
            tiktok_url=data.tiktok_url,
            caption=data.caption or "",
        )

        upload_dir = Path("uploads") / brand["slug"] / f"post_{post_id}"
        download_result = await tiktok_scraper.download_tiktok_slides(
            data.tiktok_url, str(upload_dir)
        )

        slide_paths = download_result["slides"]
        if download_result["caption"] and not data.caption:
            await db.update_post(database, post_id, caption=download_result["caption"])
        if download_result["sound_id"]:
            await db.update_post(database, post_id, tiktok_sound_id=download_result["sound_id"])

        if slide_paths:
            ocr_results = ocr.extract_slide_texts(slide_paths)
        else:
            ocr_results = []

        accounts = await db.get_accounts(database, data.brand_id)

        for i, slide_path in enumerate(slide_paths):
            ocr_data = ocr_results[i] if i < len(ocr_results) else {}
            slide_type = ocr_data.get("type", "content")
            if i == 0:
                slide_type = "hook"
            elif i == len(slide_paths) - 1:
                slide_type = "cta"

            slide_id = await db.create_slide(
                database, post_id,
                slide_number=i + 1,
                type=slide_type,
                has_face=ocr_data.get("has_face", False),
                title_text=ocr_data.get("title_text", ""),
                body_text=ocr_data.get("body_text", ""),
                cta_text=ocr_data.get("cta_text", ""),
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

        if slide_paths:
            ocr_results = ocr.extract_slide_texts(slide_paths)
        else:
            ocr_results = []

        accounts = await db.get_accounts(database, brand_id)

        for i, slide_path in enumerate(slide_paths):
            ocr_data = ocr_results[i] if i < len(ocr_results) else {}
            slide_type = ocr_data.get("type", "content")
            if i == 0:
                slide_type = "hook"
            elif i == len(slide_paths) - 1:
                slide_type = "cta"

            slide_id = await db.create_slide(
                database, post_id,
                slide_number=i + 1,
                type=slide_type,
                has_face=ocr_data.get("has_face", False),
                title_text=ocr_data.get("title_text", ""),
                body_text=ocr_data.get("body_text", ""),
                cta_text=ocr_data.get("cta_text", ""),
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
        if user["role"] == "admin":
            query = "SELECT p.*, b.name as brand_name, b.slug as brand_slug FROM posts p JOIN brands b ON p.brand_id = b.id WHERE p.status IN ('scheduled', 'generating', 'posting')"
            params = []
        else:
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
        if user["role"] == "admin":
            tracks = await db.get_music_tracks(database)
        else:
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
    return FileResponse(str(full_path))


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
