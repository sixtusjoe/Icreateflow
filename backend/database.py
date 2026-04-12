import aiosqlite
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "icreate.db"

# Fall back to zagged.db if icreate.db doesn't exist yet (migration)
if not DB_PATH.exists():
    _old = Path(__file__).parent / "zagged.db"
    if _old.exists():
        import shutil
        shutil.copy2(_old, DB_PATH)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'suspended')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    background_color TEXT DEFAULT '#000000',
    timezone TEXT DEFAULT 'US/Eastern',
    default_post_times TEXT DEFAULT '09:00,13:00,18:00',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'variation' CHECK(role IN ('master', 'variation')),
    tiktok_handle TEXT,
    youtube_handle TEXT,
    instagram_handle TEXT,
    facebook_handle TEXT,
    tiktok_token TEXT,
    youtube_token TEXT,
    instagram_token TEXT,
    facebook_token TEXT
);

CREATE TABLE IF NOT EXISTS music_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    genre TEXT,
    file_path TEXT NOT NULL,
    duration REAL,
    is_custom BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    post_number INTEGER NOT NULL,
    caption TEXT,
    tiktok_url TEXT,
    tiktok_sound_id TEXT,
    music_track_id INTEGER REFERENCES music_tracks(id),
    scheduled_time TEXT,
    scheduled_at TIMESTAMP,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft','scheduled','generating','posting','posted','failed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    slide_number INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('hook', 'content', 'cta')),
    has_face BOOLEAN DEFAULT FALSE,
    title_text TEXT,
    body_text TEXT,
    cta_text TEXT,
    master_image_path TEXT
);

CREATE TABLE IF NOT EXISTS variations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slide_id INTEGER NOT NULL REFERENCES slides(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    action TEXT DEFAULT 'keep' CHECK(action IN ('keep', 'replace', 'generate')),
    replacement_image_path TEXT,
    generated_prompt TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'generated', 'approved'))
);

CREATE TABLE IF NOT EXISTS outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    slides_dir TEXT,
    video_path TEXT,
    posting_status TEXT DEFAULT 'pending',
    tiktok_posted BOOLEAN DEFAULT FALSE,
    youtube_posted BOOLEAN DEFAULT FALSE,
    instagram_posted BOOLEAN DEFAULT FALSE,
    facebook_posted BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    UNIQUE(user_id, key)
);

CREATE TABLE IF NOT EXISTS site_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    database = await get_db()
    try:
        await database.executescript(SCHEMA)
        await database.commit()
        # Run migration for existing data
        await _migrate(database)
    finally:
        await database.close()


async def _migrate(database):
    """Add missing columns to existing tables and create default admin."""
    # Add user_id to brands if missing
    try:
        await database.execute("SELECT user_id FROM brands LIMIT 1")
    except Exception:
        await database.execute("ALTER TABLE brands ADD COLUMN user_id INTEGER REFERENCES users(id)")
        await database.commit()

    # Add user_id and is_public to music_tracks if missing
    try:
        await database.execute("SELECT user_id FROM music_tracks LIMIT 1")
    except Exception:
        await database.execute("ALTER TABLE music_tracks ADD COLUMN user_id INTEGER REFERENCES users(id)")
        await database.commit()

    try:
        await database.execute("SELECT is_public FROM music_tracks LIMIT 1")
    except Exception:
        await database.execute("ALTER TABLE music_tracks ADD COLUMN is_public BOOLEAN DEFAULT FALSE")
        await database.commit()

    # Create default admin if no users exist
    cursor = await database.execute("SELECT COUNT(*) as count FROM users")
    count = (await cursor.fetchone())["count"]
    if count == 0:
        from services.auth import hash_password
        admin_hash = hash_password("admin123")
        await database.execute(
            "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
            ("admin@icreate.com", admin_hash, "Admin", "admin")
        )
        await database.commit()

        # Assign existing brands to admin user
        admin_cursor = await database.execute("SELECT id FROM users WHERE email = 'admin@icreate.com'")
        admin = await admin_cursor.fetchone()
        if admin:
            await database.execute("UPDATE brands SET user_id = ? WHERE user_id IS NULL", (admin["id"],))
            await database.execute("UPDATE music_tracks SET user_id = ? WHERE user_id IS NULL", (admin["id"],))
            await database.commit()

    # Seed default site config
    cursor = await database.execute("SELECT COUNT(*) as count FROM site_config")
    count = (await cursor.fetchone())["count"]
    if count == 0:
        await database.execute("INSERT OR IGNORE INTO site_config (key, value) VALUES ('site_name', 'ICREATE')")
        await database.commit()


# --- User CRUD ---

async def create_user(db, email: str, password_hash: str, name: str, role: str = "user"):
    cursor = await db.execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        (email, password_hash, name, role)
    )
    await db.commit()
    return cursor.lastrowid


async def get_user_by_email(db, email: str):
    cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
    return await cursor.fetchone()


async def get_user(db, user_id: int):
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return await cursor.fetchone()


async def get_users(db):
    cursor = await db.execute("SELECT id, email, name, role, status, created_at, last_login FROM users ORDER BY created_at DESC")
    return await cursor.fetchall()


async def update_user(db, user_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    await db.execute(f"UPDATE users SET {sets} WHERE id = ?", vals)
    await db.commit()


# --- User Settings ---

async def get_user_setting(db, user_id: int, key: str, default: str = None):
    cursor = await db.execute(
        "SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)
    )
    row = await cursor.fetchone()
    return row["value"] if row else default


async def set_user_setting(db, user_id: int, key: str, value: str):
    await db.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
        (user_id, key, value)
    )
    await db.commit()


async def get_user_settings(db, user_id: int):
    cursor = await db.execute("SELECT key, value FROM user_settings WHERE user_id = ?", (user_id,))
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


# --- Site Config ---

async def get_site_config(db):
    cursor = await db.execute("SELECT * FROM site_config")
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


async def set_site_config(db, key: str, value: str):
    await db.execute(
        "INSERT OR REPLACE INTO site_config (key, value) VALUES (?, ?)", (key, value)
    )
    await db.commit()


# --- Brand CRUD ---

async def create_brand(db, name: str, slug: str, background_color: str = "#000000",
                       timezone: str = "US/Eastern", default_post_times: str = "09:00,13:00,18:00",
                       user_id: int = None):
    cursor = await db.execute(
        "INSERT INTO brands (name, slug, background_color, timezone, default_post_times, user_id) VALUES (?, ?, ?, ?, ?, ?)",
        (name, slug, background_color, timezone, default_post_times, user_id)
    )
    await db.commit()
    return cursor.lastrowid


async def get_brands(db, user_id: int = None):
    if user_id:
        cursor = await db.execute("SELECT * FROM brands WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    else:
        cursor = await db.execute("SELECT * FROM brands ORDER BY created_at DESC")
    return await cursor.fetchall()


async def get_brand(db, brand_id: int):
    cursor = await db.execute("SELECT * FROM brands WHERE id = ?", (brand_id,))
    return await cursor.fetchone()


async def update_brand(db, brand_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [brand_id]
    await db.execute(f"UPDATE brands SET {sets} WHERE id = ?", vals)
    await db.commit()


async def delete_brand(db, brand_id: int):
    await db.execute("DELETE FROM brands WHERE id = ?", (brand_id,))
    await db.commit()


# --- Account CRUD ---

async def create_account(db, brand_id: int, name: str, role: str = "variation", **kwargs):
    cols = ["brand_id", "name", "role"] + list(kwargs.keys())
    vals = [brand_id, name, role] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_str = ", ".join(cols)
    cursor = await db.execute(f"INSERT INTO accounts ({col_str}) VALUES ({placeholders})", vals)
    await db.commit()
    return cursor.lastrowid


async def get_accounts(db, brand_id: int):
    cursor = await db.execute(
        "SELECT * FROM accounts WHERE brand_id = ? ORDER BY role DESC, id", (brand_id,)
    )
    return await cursor.fetchall()


async def get_account(db, account_id: int):
    cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    return await cursor.fetchone()


async def update_account(db, account_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [account_id]
    await db.execute(f"UPDATE accounts SET {sets} WHERE id = ?", vals)
    await db.commit()


async def delete_account(db, account_id: int):
    await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    await db.commit()


# --- Post CRUD ---

async def create_post(db, brand_id: int, date: str, post_number: int, **kwargs):
    cols = ["brand_id", "date", "post_number"] + list(kwargs.keys())
    vals = [brand_id, date, post_number] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_str = ", ".join(cols)
    cursor = await db.execute(f"INSERT INTO posts ({col_str}) VALUES ({placeholders})", vals)
    await db.commit()
    return cursor.lastrowid


async def get_posts(db, brand_id: int = None, date: str = None, user_id: int = None):
    if user_id:
        query = "SELECT p.* FROM posts p JOIN brands b ON p.brand_id = b.id WHERE b.user_id = ?"
        params = [user_id]
    else:
        query = "SELECT * FROM posts WHERE 1=1"
        params = []
    if brand_id:
        query += " AND brand_id = ?"  if not user_id else " AND p.brand_id = ?"
        params.append(brand_id)
    if date:
        query += " AND date = ?" if not user_id else " AND p.date = ?"
        params.append(date)
    query += " ORDER BY date DESC, post_number" if not user_id else " ORDER BY p.date DESC, p.post_number"
    cursor = await db.execute(query, params)
    return await cursor.fetchall()


async def get_post(db, post_id: int):
    cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
    return await cursor.fetchone()


async def update_post(db, post_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [post_id]
    await db.execute(f"UPDATE posts SET {sets} WHERE id = ?", vals)
    await db.commit()


# --- Slide CRUD ---

async def create_slide(db, post_id: int, slide_number: int, type: str, **kwargs):
    cols = ["post_id", "slide_number", "type"] + list(kwargs.keys())
    vals = [post_id, slide_number, type] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_str = ", ".join(cols)
    cursor = await db.execute(f"INSERT INTO slides ({col_str}) VALUES ({placeholders})", vals)
    await db.commit()
    return cursor.lastrowid


async def get_slides(db, post_id: int):
    cursor = await db.execute(
        "SELECT * FROM slides WHERE post_id = ? ORDER BY slide_number", (post_id,)
    )
    return await cursor.fetchall()


async def update_slide(db, slide_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [slide_id]
    await db.execute(f"UPDATE slides SET {sets} WHERE id = ?", vals)
    await db.commit()


# --- Variation CRUD ---

async def create_variation(db, slide_id: int, account_id: int, action: str = "keep", **kwargs):
    cols = ["slide_id", "account_id", "action"] + list(kwargs.keys())
    vals = [slide_id, account_id, action] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_str = ", ".join(cols)
    cursor = await db.execute(f"INSERT INTO variations ({col_str}) VALUES ({placeholders})", vals)
    await db.commit()
    return cursor.lastrowid


async def get_variations(db, post_id: int = None, account_id: int = None):
    query = """
        SELECT v.* FROM variations v
        JOIN slides s ON v.slide_id = s.id
        WHERE 1=1
    """
    params = []
    if post_id:
        query += " AND s.post_id = ?"
        params.append(post_id)
    if account_id:
        query += " AND v.account_id = ?"
        params.append(account_id)
    query += " ORDER BY s.slide_number"
    cursor = await db.execute(query, params)
    return await cursor.fetchall()


async def update_variation(db, variation_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [variation_id]
    await db.execute(f"UPDATE variations SET {sets} WHERE id = ?", vals)
    await db.commit()


# --- Output CRUD ---

async def create_output(db, post_id: int, account_id: int, **kwargs):
    cols = ["post_id", "account_id"] + list(kwargs.keys())
    vals = [post_id, account_id] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_str = ", ".join(cols)
    cursor = await db.execute(f"INSERT INTO outputs ({col_str}) VALUES ({placeholders})", vals)
    await db.commit()
    return cursor.lastrowid


async def get_outputs(db, post_id: int):
    cursor = await db.execute(
        "SELECT * FROM outputs WHERE post_id = ? ORDER BY account_id", (post_id,)
    )
    return await cursor.fetchall()


async def update_output(db, output_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [output_id]
    await db.execute(f"UPDATE outputs SET {sets} WHERE id = ?", vals)
    await db.commit()


# --- Music Track CRUD ---

async def create_music_track(db, name: str, file_path: str, genre: str = None,
                              duration: float = None, is_custom: bool = False,
                              user_id: int = None, is_public: bool = False):
    cursor = await db.execute(
        "INSERT INTO music_tracks (name, genre, file_path, duration, is_custom, user_id, is_public) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, genre, file_path, duration, is_custom, user_id, is_public)
    )
    await db.commit()
    return cursor.lastrowid


async def get_music_tracks(db, user_id: int = None):
    if user_id:
        cursor = await db.execute(
            "SELECT * FROM music_tracks WHERE user_id = ? OR is_public = 1 ORDER BY name", (user_id,)
        )
    else:
        cursor = await db.execute("SELECT * FROM music_tracks ORDER BY name")
    return await cursor.fetchall()


async def delete_music_track(db, track_id: int):
    cursor = await db.execute("SELECT file_path FROM music_tracks WHERE id = ?", (track_id,))
    track = await cursor.fetchone()
    if track and os.path.exists(track["file_path"]):
        os.remove(track["file_path"])
    await db.execute("DELETE FROM music_tracks WHERE id = ?", (track_id,))
    await db.commit()


# --- Settings (global) ---

async def get_setting(db, key: str, default: str = None):
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


async def set_setting(db, key: str, value: str):
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    await db.commit()
