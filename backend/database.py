"""ICREATEFLOW database layer — SQLAlchemy 2.0 async + Postgres (asyncpg driver).

Design:
  * ORM models define the schema (source of truth for `init_db`).
  * `get_db()` returns a `Connection` wrapper that keeps the legacy
    aiosqlite-style API (`await db.execute("SELECT ... WHERE x = ?", (val,))`,
    `row["col"]`, `cursor.lastrowid`) working so existing callers in main.py
    don't need rewriting. Under the hood every call goes through an
    `AsyncSession`, so we get SQLAlchemy's connection pool, transaction
    management, and typed drivers.
  * CRUD helpers are reimplemented using SQLAlchemy expression constructs
    (`select()`, `insert().returning()`, etc.) as reference usage for new code.

Backwards-compat translations applied inside `Connection.execute`:
  * `?` positional placeholders → `:p1, :p2, …`
  * `INSERT OR IGNORE INTO …`   → `INSERT INTO … ON CONFLICT DO NOTHING`
  * `INSERT OR REPLACE INTO t (cols) VALUES (…)` → upsert on the table's PK
  * `PRAGMA …`                  → no-op
  * Boolean columns: 0/1 params and `= 0|1` literals coerced to real bools
  * INSERTs without `RETURNING` get `RETURNING id` appended so `lastrowid` works
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Double,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_DSN = os.environ.get(
    "ICREATE_DB_DSN",
    "postgresql+asyncpg://{user}@127.0.0.1:5432/icreateflow".format(
        user=os.environ.get("PGUSER", os.environ.get("USER", "postgres"))
    ),
)

# Kept so the sqlite→postgres migration script can still find the old file.
DB_PATH = Path(__file__).parent / "icreate.db"

# Columns stored as Postgres TIMESTAMP — ISO strings coming from callers need
# to be parsed into `datetime` since asyncpg rejects str for timestamp binds.
_TIMESTAMP_COLUMNS = {"created_at", "last_login", "scheduled_at"}

# Columns that must always be coerced to real booleans regardless of input form.
_BOOLEAN_COLUMNS = {
    "is_custom",
    "is_public",
    "has_face",
    "tiktok_posted",
    "youtube_posted",
    "instagram_posted",
    "facebook_posted",
}

# INSERT OR REPLACE conflict targets per table
_REPLACE_CONFLICT_TARGETS = {
    "settings": "(key)",
    "site_config": "(key)",
    "user_settings": "(user_id, key)",
}

# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, server_default="user")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    last_login: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="users_role_chk"),
        CheckConstraint("status IN ('active', 'suspended')", name="users_status_chk"),
    )


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    background_color: Mapped[str] = mapped_column(Text, server_default="#000000")
    timezone: Mapped[str] = mapped_column(Text, server_default="US/Eastern")
    default_post_times: Mapped[str] = mapped_column(Text, server_default="09:00,13:00,18:00")
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, server_default="variation")
    tiktok_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (CheckConstraint("role IN ('master', 'variation')", name="accounts_role_chk"),)


class MusicTrack(Base):
    __tablename__ = "music_tracks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    genre: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_public: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    post_number: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_sound_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    music_track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("music_tracks.id"), nullable=True)
    scheduled_time: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','generating','posting','posted','failed')",
            name="posts_status_chk",
        ),
    )


class Slide(Base):
    __tablename__ = "slides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    slide_number: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    has_face: Mapped[bool] = mapped_column(Boolean, server_default="false")
    title_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cta_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    master_image_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (CheckConstraint("type IN ('hook', 'content', 'cta')", name="slides_type_chk"),)


class Variation(Base):
    __tablename__ = "variations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slide_id: Mapped[int] = mapped_column(ForeignKey("slides.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(Text, server_default="keep")
    replacement_image_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    __table_args__ = (
        CheckConstraint("action IN ('keep', 'replace', 'generate')", name="variations_action_chk"),
        CheckConstraint(
            "status IN ('pending', 'generated', 'approved')", name="variations_status_chk"
        ),
    )


class Output(Base):
    __tablename__ = "outputs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    slides_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    posting_status: Mapped[str] = mapped_column(Text, server_default="pending")
    tiktok_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    youtube_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    instagram_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    facebook_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UserSetting(Base):
    __tablename__ = "user_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "key", name="user_settings_uidkey_uniq"),)


class SiteConfig(Base):
    __tablename__ = "site_config"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------

engine = create_async_engine(DB_DSN, pool_pre_ping=True, future=True)
_Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# ---------------------------------------------------------------------------
# SQL translation (SQLite dialect → Postgres via SQLAlchemy text())
# ---------------------------------------------------------------------------


def _translate_placeholders(sql: str) -> tuple[str, list[str]]:
    """Convert `?` positional placeholders → `:p1, :p2, …`. Return (sql, names)."""
    out: list[str] = []
    names: list[str] = []
    in_s = in_d = False
    i = 0
    n = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_d:
            in_s = not in_s
            out.append(ch)
        elif ch == '"' and not in_s:
            in_d = not in_d
            out.append(ch)
        elif ch == "?" and not in_s and not in_d:
            n += 1
            name = f"p{n}"
            out.append(f":{name}")
            names.append(name)
        else:
            out.append(ch)
        i += 1
    return "".join(out), names


def _translate_sqlite_isms(sql: str) -> str:
    s = sql

    def _replace_upsert(match: re.Match) -> str:
        table = match.group(1)
        cols_raw = match.group(2)
        vals_raw = match.group(3)
        cols = [c.strip() for c in cols_raw.split(",")]
        conflict = _REPLACE_CONFLICT_TARGETS.get(table.lower(), "(id)")
        target_cols = {c.strip() for c in conflict.strip("()").split(",")}
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in target_cols)
        on_conflict = (
            f"ON CONFLICT {conflict} DO UPDATE SET {updates}"
            if updates
            else f"ON CONFLICT {conflict} DO NOTHING"
        )
        return f"INSERT INTO {table} ({cols_raw}) VALUES ({vals_raw}) {on_conflict}"

    s = re.sub(
        r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
        _replace_upsert,
        s,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bOR\s+IGNORE\b", sql, re.IGNORECASE):
        s = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT", s, flags=re.IGNORECASE)
        if "ON CONFLICT" not in s.upper():
            s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return s


def _rewrite_boolean_literals(sql: str) -> str:
    def _repl(m: re.Match) -> str:
        col, val = m.group(1), m.group(2)
        if col in _BOOLEAN_COLUMNS:
            return f"{col} = {'TRUE' if val == '1' else 'FALSE'}"
        return m.group(0)

    return re.sub(r"(\b\w+)\s*=\s*([01])\b", _repl, sql)


def _parse_timestamp(val: Any) -> Any:
    if val is None or isinstance(val, datetime):
        return val
    if not isinstance(val, str):
        return val
    s = val.strip().replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1]
    # strip timezone offset ("2026-04-18 06:12:32.187155+00:00" → drop "+00:00")
    if len(s) > 10 and ("+" in s[10:] or "-" in s[19:]):
        # be conservative — only strip a trailing "+HH:MM" or "-HH:MM"
        m = re.search(r"([+-])\d{2}:?\d{2}$", s)
        if m:
            s = s[: m.start()]
    s = s.rstrip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return val


def _coerce_timestamp_params(sql: str, names: list[str], values: list[Any]) -> list[Any]:
    if not values:
        return values
    out = list(values)
    # INSERT INTO t (c1, c2) VALUES (:p1, :p2)
    m = re.search(
        r"\bINSERT\s+INTO\s+\w+\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)", sql, re.IGNORECASE
    )
    if m:
        col_list = [c.strip() for c in m.group(1).split(",")]
        val_list = [v.strip() for v in m.group(2).split(",")]
        for col, val in zip(col_list, val_list):
            if col in _TIMESTAMP_COLUMNS and val.startswith(":"):
                try:
                    idx = names.index(val[1:])
                    out[idx] = _parse_timestamp(out[idx])
                except (ValueError, IndexError):
                    pass
    for match in re.finditer(r"(\w+)\s*=\s*:(\w+)", sql):
        col, name = match.group(1), match.group(2)
        if col in _TIMESTAMP_COLUMNS:
            try:
                idx = names.index(name)
                out[idx] = _parse_timestamp(out[idx])
            except (ValueError, IndexError):
                pass
    return out


def _coerce_boolean_params(sql: str, names: list[str], values: list[Any]) -> list[Any]:
    """Coerce 0/1/'0'/'1'/'true'/'false' → bool for BOOLEAN columns."""
    if not values:
        return values
    out = list(values)
    # INSERT INTO t (c1, c2, ...) VALUES (:p1, :p2, ...)
    m = re.search(
        r"\bINSERT\s+INTO\s+\w+\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)", sql, re.IGNORECASE
    )
    if m:
        col_list = [c.strip() for c in m.group(1).split(",")]
        val_list = [v.strip() for v in m.group(2).split(",")]
        for col, val in zip(col_list, val_list):
            if col in _BOOLEAN_COLUMNS and val.startswith(":"):
                try:
                    idx = names.index(val[1:])
                    v = out[idx]
                    if v in (0, 1, "0", "1"):
                        out[idx] = bool(int(v))
                    elif isinstance(v, str) and v.lower() in ("true", "false"):
                        out[idx] = v.lower() == "true"
                except (ValueError, IndexError):
                    pass
    # `col = :pN` in SET / WHERE clauses
    for match in re.finditer(r"(\w+)\s*=\s*:(\w+)", sql):
        col, name = match.group(1), match.group(2)
        if col in _BOOLEAN_COLUMNS:
            try:
                idx = names.index(name)
                v = out[idx]
                if v in (0, 1, "0", "1"):
                    out[idx] = bool(int(v))
                elif isinstance(v, str) and v.lower() in ("true", "false"):
                    out[idx] = v.lower() == "true"
            except (ValueError, IndexError):
                pass
    return out


def _translate(sql: str, params: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    s = _translate_sqlite_isms(sql)
    s = _rewrite_boolean_literals(s)
    s, names = _translate_placeholders(s)
    values = list(params or [])
    values = _coerce_boolean_params(s, names, values)
    values = _coerce_timestamp_params(s, names, values)

    stripped = s.strip().upper()
    if (
        stripped.startswith("INSERT")
        and "RETURNING" not in stripped
        and "INTO SETTINGS" not in stripped
        and "INTO SITE_CONFIG" not in stripped
    ):
        s = s.rstrip().rstrip(";") + " RETURNING id"

    return s, {name: val for name, val in zip(names, values)}


# ---------------------------------------------------------------------------
# Row / Cursor / Connection shims over AsyncSession
# ---------------------------------------------------------------------------


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _Cursor:
    def __init__(self, rows: list[Row], lastrowid: Optional[int] = None):
        self._rows = rows
        self.lastrowid = lastrowid

    async def fetchone(self) -> Optional[Row]:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[Row]:
        return list(self._rows)

    async def close(self) -> None:
        self._rows = []


class Connection:
    """SQLAlchemy AsyncSession wrapped with the legacy aiosqlite-style API."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self.row_factory = None  # unused; we always return Row dicts

    @property
    def session(self) -> AsyncSession:
        """Expose the underlying AsyncSession for new ORM-based code."""
        return self._session

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> _Cursor:
        if sql.strip().upper().startswith("PRAGMA"):
            return _Cursor([])
        translated, param_map = _translate(sql, list(params) if params else [])
        stripped = translated.strip().upper()
        result = await self._session.execute(text(translated), param_map)

        if stripped.startswith("INSERT") and "RETURNING" in stripped:
            first = result.first()
            lastrowid = first[0] if first else None
            return _Cursor([], lastrowid=lastrowid)
        if stripped.startswith(("SELECT", "WITH", "VALUES")):
            return _Cursor([Row(m) for m in result.mappings().all()])
        return _Cursor([])

    async def executescript(self, script: str) -> None:
        for stmt in re.split(r";\s*(?:\n|$)", script):
            s = stmt.strip()
            if s:
                await self._session.execute(text(s))

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def close(self) -> None:
        await self._session.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_db() -> Connection:
    session = _Session()
    return Connection(session)


OAUTH_ACCOUNT_COLUMNS = [
    "tiktok_refresh_token", "tiktok_expires_at", "tiktok_scopes", "tiktok_user_id",
    "youtube_refresh_token", "youtube_expires_at", "youtube_scopes", "youtube_user_id",
    "instagram_refresh_token", "instagram_expires_at", "instagram_scopes", "instagram_user_id",
    "facebook_refresh_token", "facebook_expires_at", "facebook_scopes", "facebook_user_id",
]


async def _migrate_oauth_columns(conn) -> None:
    """Idempotently add OAuth-related columns to accounts (Postgres)."""
    for col in OAUTH_ACCOUNT_COLUMNS:
        await conn.execute(text(f'ALTER TABLE accounts ADD COLUMN IF NOT EXISTS {col} TEXT'))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_oauth_columns(conn)
    db = await get_db()
    try:
        await _seed(db)
    finally:
        await db.close()


async def _seed(db: Connection) -> None:
    """Seed default admin + site_config on an empty database."""
    s = db.session
    count = (await s.execute(select(func.count()).select_from(User))).scalar_one()
    if count == 0:
        from services.auth import hash_password

        admin_hash = hash_password("admin123")
        await s.execute(
            insert(User).values(
                email="admin@icreate.com", password_hash=admin_hash, name="Admin", role="admin"
            )
        )
        await s.commit()
        admin = (
            await s.execute(select(User.id).where(User.email == "admin@icreate.com"))
        ).scalar_one_or_none()
        if admin is not None:
            await s.execute(update(Brand).where(Brand.user_id.is_(None)).values(user_id=admin))
            await s.execute(update(MusicTrack).where(MusicTrack.user_id.is_(None)).values(user_id=admin))
            await s.commit()

    sc_count = (await s.execute(select(func.count()).select_from(SiteConfig))).scalar_one()
    if sc_count == 0:
        await s.execute(
            text(
                "INSERT INTO site_config (key, value) VALUES ('site_name', 'ICREATEFLOW') "
                "ON CONFLICT (key) DO NOTHING"
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# CRUD helpers — SQLAlchemy ORM
# ---------------------------------------------------------------------------


def _prep(kwargs: dict) -> dict:
    """Normalize ORM kwargs: parse ISO-string timestamps, coerce booleans."""
    out = {}
    for k, v in kwargs.items():
        if k in _TIMESTAMP_COLUMNS:
            out[k] = _parse_timestamp(v)
        elif k in _BOOLEAN_COLUMNS and isinstance(v, (int, str)) and not isinstance(v, bool):
            if v in (0, 1, "0", "1"):
                out[k] = bool(int(v))
            elif isinstance(v, str) and v.lower() in ("true", "false"):
                out[k] = v.lower() == "true"
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _row(obj) -> Optional[Row]:
    if obj is None:
        return None
    if isinstance(obj, Row):
        return obj
    # SQLAlchemy RowMapping is a Mapping — check via keys() before touching attributes.
    if hasattr(obj, "keys") and callable(getattr(obj, "keys", None)):
        try:
            return Row({k: obj[k] for k in obj.keys()})
        except Exception:  # noqa: BLE001
            pass
    if hasattr(obj, "_mapping"):
        return Row(obj._mapping)
    if isinstance(obj, dict):
        return Row(obj)
    # ORM model instance
    return Row({c.name: getattr(obj, c.name) for c in obj.__table__.columns})


def _rows(objs) -> list[Row]:
    return [_row(o) for o in objs]


# --- Users ---

async def create_user(db: Connection, email: str, password_hash: str, name: str, role: str = "user"):
    s = db.session
    stmt = insert(User).values(email=email, password_hash=password_hash, name=name, role=role).returning(User.id)
    user_id = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return user_id


async def get_user_by_email(db: Connection, email: str):
    s = db.session
    obj = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
    return _row(obj)


async def get_user(db: Connection, user_id: int):
    s = db.session
    obj = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    return _row(obj)


async def get_users(db: Connection):
    s = db.session
    result = await s.execute(
        select(
            User.id, User.email, User.name, User.role, User.status, User.created_at, User.last_login
        ).order_by(User.created_at.desc())
    )
    return _rows(result.mappings().all())


async def update_user(db: Connection, user_id: int, **kwargs):
    s = db.session
    await s.execute(update(User).where(User.id == user_id).values(**_prep(kwargs)))
    await s.commit()


# --- User settings ---

async def get_user_setting(db: Connection, user_id: int, key: str, default: str | None = None):
    s = db.session
    val = (
        await s.execute(
            select(UserSetting.value).where(UserSetting.user_id == user_id, UserSetting.key == key)
        )
    ).scalar_one_or_none()
    return val if val is not None else default


async def set_user_setting(db: Connection, user_id: int, key: str, value: str):
    s = db.session
    await s.execute(
        text(
            "INSERT INTO user_settings (user_id, key, value) VALUES (:uid, :k, :v) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"uid": user_id, "k": key, "v": value},
    )
    await s.commit()


async def get_user_settings(db: Connection, user_id: int):
    s = db.session
    rows = (
        await s.execute(
            select(UserSetting.key, UserSetting.value).where(UserSetting.user_id == user_id)
        )
    ).all()
    return {r.key: r.value for r in rows}


# --- Site config ---

async def get_site_config(db: Connection):
    s = db.session
    rows = (await s.execute(select(SiteConfig.key, SiteConfig.value))).all()
    return {r.key: r.value for r in rows}


async def set_site_config(db: Connection, key: str, value: str):
    s = db.session
    await s.execute(
        text(
            "INSERT INTO site_config (key, value) VALUES (:k, :v) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"k": key, "v": value},
    )
    await s.commit()


# --- Brands ---

async def create_brand(
    db: Connection,
    name: str,
    slug: str,
    background_color: str = "#000000",
    timezone: str = "US/Eastern",
    default_post_times: str = "09:00,13:00,18:00",
    user_id: int | None = None,
):
    s = db.session
    stmt = (
        insert(Brand)
        .values(
            name=name,
            slug=slug,
            background_color=background_color,
            timezone=timezone,
            default_post_times=default_post_times,
            user_id=user_id,
        )
        .returning(Brand.id)
    )
    bid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return bid


async def get_brands(db: Connection, user_id: int | None = None):
    s = db.session
    stmt = select(Brand)
    if user_id:
        stmt = stmt.where(Brand.user_id == user_id)
    stmt = stmt.order_by(Brand.created_at.desc())
    return _rows((await s.execute(stmt)).scalars().all())


async def get_brand(db: Connection, brand_id: int):
    s = db.session
    return _row((await s.execute(select(Brand).where(Brand.id == brand_id))).scalar_one_or_none())


async def update_brand(db: Connection, brand_id: int, **kwargs):
    s = db.session
    await s.execute(update(Brand).where(Brand.id == brand_id).values(**_prep(kwargs)))
    await s.commit()


async def delete_brand(db: Connection, brand_id: int):
    s = db.session
    await s.execute(delete(Brand).where(Brand.id == brand_id))
    await s.commit()


# --- Accounts ---

async def create_account(db: Connection, brand_id: int, name: str, role: str = "variation", **kwargs):
    s = db.session
    stmt = (
        insert(Account)
        .values(brand_id=brand_id, name=name, role=role, **_prep(kwargs))
        .returning(Account.id)
    )
    aid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return aid


async def get_accounts(db: Connection, brand_id: int):
    s = db.session
    rows = await s.execute(
        select(Account).where(Account.brand_id == brand_id).order_by(Account.role.desc(), Account.id)
    )
    return _rows(rows.scalars().all())


async def get_account(db: Connection, account_id: int):
    s = db.session
    return _row(
        (await s.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    )


async def update_account(db: Connection, account_id: int, **kwargs):
    s = db.session
    await s.execute(update(Account).where(Account.id == account_id).values(**_prep(kwargs)))
    await s.commit()


async def delete_account(db: Connection, account_id: int):
    s = db.session
    await s.execute(delete(Account).where(Account.id == account_id))
    await s.commit()


# --- Posts ---

async def create_post(db: Connection, brand_id: int, date: str, post_number: int, **kwargs):
    s = db.session
    stmt = (
        insert(Post)
        .values(brand_id=brand_id, date=date, post_number=post_number, **_prep(kwargs))
        .returning(Post.id)
    )
    pid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return pid


async def get_posts(
    db: Connection, brand_id: int | None = None, date: str | None = None, user_id: int | None = None
):
    s = db.session
    stmt = select(Post)
    if user_id:
        stmt = stmt.join(Brand, Post.brand_id == Brand.id).where(Brand.user_id == user_id)
    if brand_id:
        stmt = stmt.where(Post.brand_id == brand_id)
    if date:
        stmt = stmt.where(Post.date == date)
    stmt = stmt.order_by(Post.date.desc(), Post.post_number)
    rows = await s.execute(stmt)
    return _rows(rows.scalars().all())


async def get_post(db: Connection, post_id: int):
    s = db.session
    return _row((await s.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none())


async def update_post(db: Connection, post_id: int, **kwargs):
    s = db.session
    await s.execute(update(Post).where(Post.id == post_id).values(**_prep(kwargs)))
    await s.commit()


# --- Slides ---

async def create_slide(db: Connection, post_id: int, slide_number: int, type: str, **kwargs):
    s = db.session
    stmt = (
        insert(Slide)
        .values(post_id=post_id, slide_number=slide_number, type=type, **_prep(kwargs))
        .returning(Slide.id)
    )
    sid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return sid


async def get_slides(db: Connection, post_id: int):
    s = db.session
    rows = await s.execute(
        select(Slide).where(Slide.post_id == post_id).order_by(Slide.slide_number)
    )
    return _rows(rows.scalars().all())


async def update_slide(db: Connection, slide_id: int, **kwargs):
    s = db.session
    await s.execute(update(Slide).where(Slide.id == slide_id).values(**_prep(kwargs)))
    await s.commit()


# --- Variations ---

async def create_variation(db: Connection, slide_id: int, account_id: int, action: str = "keep", **kwargs):
    s = db.session
    stmt = (
        insert(Variation)
        .values(slide_id=slide_id, account_id=account_id, action=action, **_prep(kwargs))
        .returning(Variation.id)
    )
    vid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return vid


async def get_variations(db: Connection, post_id: int | None = None, account_id: int | None = None):
    s = db.session
    stmt = select(Variation).join(Slide, Variation.slide_id == Slide.id)
    if post_id:
        stmt = stmt.where(Slide.post_id == post_id)
    if account_id:
        stmt = stmt.where(Variation.account_id == account_id)
    stmt = stmt.order_by(Slide.slide_number)
    rows = await s.execute(stmt)
    return _rows(rows.scalars().all())


async def update_variation(db: Connection, variation_id: int, **kwargs):
    s = db.session
    await s.execute(update(Variation).where(Variation.id == variation_id).values(**_prep(kwargs)))
    await s.commit()


# --- Outputs ---

async def create_output(db: Connection, post_id: int, account_id: int, **kwargs):
    s = db.session
    stmt = (
        insert(Output)
        .values(post_id=post_id, account_id=account_id, **_prep(kwargs))
        .returning(Output.id)
    )
    oid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return oid


async def get_outputs(db: Connection, post_id: int):
    s = db.session
    rows = await s.execute(select(Output).where(Output.post_id == post_id).order_by(Output.account_id))
    return _rows(rows.scalars().all())


async def update_output(db: Connection, output_id: int, **kwargs):
    s = db.session
    await s.execute(update(Output).where(Output.id == output_id).values(**_prep(kwargs)))
    await s.commit()


# --- Music tracks ---

async def create_music_track(
    db: Connection,
    name: str,
    file_path: str,
    genre: str | None = None,
    duration: float | None = None,
    is_custom: bool = False,
    user_id: int | None = None,
    is_public: bool = False,
):
    s = db.session
    stmt = (
        insert(MusicTrack)
        .values(
            name=name,
            genre=genre,
            file_path=file_path,
            duration=duration,
            is_custom=bool(is_custom),
            user_id=user_id,
            is_public=bool(is_public),
        )
        .returning(MusicTrack.id)
    )
    mid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return mid


async def get_music_tracks(db: Connection, user_id: int | None = None):
    s = db.session
    stmt = select(MusicTrack)
    if user_id:
        stmt = stmt.where((MusicTrack.user_id == user_id) | (MusicTrack.is_public.is_(True)))
    stmt = stmt.order_by(MusicTrack.name)
    rows = await s.execute(stmt)
    return _rows(rows.scalars().all())


async def delete_music_track(db: Connection, track_id: int):
    s = db.session
    track = (
        await s.execute(select(MusicTrack.file_path).where(MusicTrack.id == track_id))
    ).scalar_one_or_none()
    if track and os.path.exists(track):
        os.remove(track)
    await s.execute(delete(MusicTrack).where(MusicTrack.id == track_id))
    await s.commit()


# --- Settings (global) ---

async def get_setting(db: Connection, key: str, default: str | None = None):
    s = db.session
    val = (await s.execute(select(Setting.value).where(Setting.key == key))).scalar_one_or_none()
    return val if val is not None else default


async def set_setting(db: Connection, key: str, value: str):
    s = db.session
    await s.execute(
        text(
            "INSERT INTO settings (key, value) VALUES (:k, :v) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"k": key, "v": value},
    )
    await s.commit()
