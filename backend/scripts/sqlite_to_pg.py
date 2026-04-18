"""Copy data from the legacy SQLite DB (backend/icreate.db) into Postgres.

Usage (from backend/ directory):
    python3 scripts/sqlite_to_pg.py

Safe to re-run: each table is truncated + reseeded from the SQLite snapshot,
and Postgres sequences are advanced to the max imported id.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

# Make `database` importable when running as `python3 scripts/sqlite_to_pg.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import DB_PATH, engine, init_db  # noqa: E402
from sqlalchemy import text  # noqa: E402

# Import order matters (parents before children) for INSERTs respecting FKs.
TABLES = [
    "users",
    "brands",
    "accounts",
    "music_tracks",
    "posts",
    "slides",
    "variations",
    "outputs",
    "settings",
    "user_settings",
    "site_config",
]

# Columns per table — these must match both schemas.
COLUMNS: dict[str, list[str]] = {
    "users": [
        "id", "email", "password_hash", "name", "role", "status", "created_at", "last_login",
    ],
    "brands": [
        "id", "user_id", "name", "slug", "background_color", "timezone",
        "default_post_times", "created_at",
    ],
    "accounts": [
        "id", "brand_id", "name", "role",
        "tiktok_handle", "youtube_handle", "instagram_handle", "facebook_handle",
        "tiktok_token", "youtube_token", "instagram_token", "facebook_token",
    ],
    "music_tracks": [
        "id", "user_id", "name", "genre", "file_path", "duration",
        "is_custom", "is_public", "created_at",
    ],
    "posts": [
        "id", "brand_id", "date", "post_number", "caption", "tiktok_url", "tiktok_sound_id",
        "music_track_id", "scheduled_time", "scheduled_at", "status", "created_at",
    ],
    "slides": [
        "id", "post_id", "slide_number", "type", "has_face",
        "title_text", "body_text", "cta_text", "master_image_path",
    ],
    "variations": [
        "id", "slide_id", "account_id", "action", "replacement_image_path",
        "generated_prompt", "status",
    ],
    "outputs": [
        "id", "post_id", "account_id", "slides_dir", "video_path", "posting_status",
        "tiktok_posted", "youtube_posted", "instagram_posted", "facebook_posted",
    ],
    "settings": ["key", "value"],
    "user_settings": ["id", "user_id", "key", "value"],
    "site_config": ["key", "value"],
}

BOOLEAN_COLUMNS = {
    "is_custom", "is_public", "has_face",
    "tiktok_posted", "youtube_posted", "instagram_posted", "facebook_posted",
}

TIMESTAMP_COLUMNS = {"created_at", "last_login", "scheduled_at"}


def _parse_ts(val):
    from datetime import datetime
    if isinstance(val, datetime):
        return val
    if not isinstance(val, str):
        return val
    s = val.strip().replace("T", " ")
    # strip timezone offset/Z that sqlite sometimes stores
    if s.endswith("Z"):
        s = s[:-1]
    if "+" in s[10:]:
        s = s.split("+", 1)[0]
    s = s.rstrip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

# Tables with a SERIAL `id` whose sequence needs resyncing after bulk load.
SERIAL_TABLES = {
    "users", "brands", "accounts", "music_tracks", "posts",
    "slides", "variations", "outputs", "user_settings",
}


def _coerce(col: str, val):
    if val is None:
        return None
    if col in BOOLEAN_COLUMNS:
        if isinstance(val, bool):
            return val
        if isinstance(val, int):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "t", "yes")
    if col in TIMESTAMP_COLUMNS:
        return _parse_ts(val)
    return val


async def main() -> None:
    if not DB_PATH.exists():
        print(f"No SQLite DB at {DB_PATH} — nothing to migrate.")
        return

    # Ensure Postgres schema exists.
    await init_db()

    sqlite_conn = sqlite3.connect(str(DB_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    async with engine.begin() as pg:
        # Disable FK checks for the duration of the import (CASCADE order is safe,
        # but this lets us truncate + reload without hunting sequence resets).
        await pg.execute(text("SET session_replication_role = 'replica'"))

        for table in TABLES:
            cols = COLUMNS[table]
            rows = sqlite_conn.execute(
                f"SELECT {', '.join(cols)} FROM {table}"
            ).fetchall()
            print(f"  {table}: {len(rows)} rows", end="")

            # Truncate destination first
            await pg.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))

            if not rows:
                print("  (empty)")
                continue

            placeholders = ", ".join(f":{c}" for c in cols)
            stmt = text(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
            )
            for r in rows:
                params = {c: _coerce(c, r[c]) for c in cols}
                await pg.execute(stmt, params)
            print("  ✓")

        # Resync serial sequences so next INSERT doesn't collide with imported ids.
        for table in SERIAL_TABLES:
            await pg.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                    f"(SELECT MAX(id) IS NOT NULL FROM {table}))"
                )
            )

        await pg.execute(text("SET session_replication_role = 'origin'"))

    sqlite_conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())
