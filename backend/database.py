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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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
_TIMESTAMP_COLUMNS = {
    "created_at", "last_login", "scheduled_at",
    "scheduled_for", "posted_at", "view_count_updated_at", "last_posted_at",
    "started_at", "ended_at", "next_scheduled_at",
    "deleted_at",
}

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
    email_notifications: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="true", nullable=True)
    unsubscribe_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="users_role_chk"),
        CheckConstraint("status IN ('active', 'suspended', 'pending')", name="users_status_chk"),
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
    tiktok_refresh_token:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_expires_at:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_scopes:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_user_id:          Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_refresh_token:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_expires_at:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_scopes:          Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_user_id:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_expires_at:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_scopes:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_user_id:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_refresh_token:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_expires_at:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_scopes:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_user_id:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Per-account residential proxy (matches Clipping's artist_accounts).
    # When set, every TikTok / YT / IG / FB call from this account is
    # routed through this URL. Critical for US-targeted accounts on
    # platforms that deprioritise datacenter IPs.
    proxy_url:               Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    platforms_allowed: Mapped[str] = mapped_column(Text, server_default="youtube,instagram,facebook")
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
    youtube_music_track_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("music_tracks.id"), nullable=True)
    instagram_music_track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("music_tracks.id"), nullable=True)
    facebook_music_track_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("music_tracks.id"), nullable=True)
    scheduled_time: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
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
    youtube_video_path:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_video_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_video_path:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    posting_status: Mapped[str] = mapped_column(Text, server_default="pending")
    tiktok_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    youtube_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    instagram_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    facebook_posted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # TikTok Direct Post per-(post, variation) settings — see
    # _migrate_per_variation_columns. All booleans default false; the
    # privacy_level column has no default by TikTok rule (user must pick).
    tiktok_post_as_draft: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_disclosure_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_disclose_your_brand: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_disclose_branded_content: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_allow_comment: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_allow_duet: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_allow_stitch: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_privacy_level: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    posted_as_draft: Mapped[bool] = mapped_column(Boolean, server_default="false")


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


class EmailOtp(Base):
    """Short-lived OTP codes for password reset and email change flows."""
    __tablename__ = "email_otps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)  # email the OTP was sent to
    code: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)  # 'password_reset' | 'email_change'
    new_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # for email_change
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())


class MetaPendingAssignment(Base):
    """Short-lived (~15 min) handoff between the Meta OAuth callback and the
    follow-up /api/oauth/meta/assign POST. Was an in-memory dict, but with
    multiple gunicorn workers the callback's worker rarely matches the assign
    POST's worker — so 50% of assignments returned 404. Move to the DB so any
    worker can read it.
    """
    __tablename__ = "meta_pending_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


# --- Clipping: Artists, Variations, Clips, ClipPosts ------------------------


class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, server_default="US/Eastern")
    posts_per_day: Mapped[int] = mapped_column(Integer, server_default="3")
    window_start: Mapped[str] = mapped_column(Text, server_default="09:00")
    window_end: Mapped[str] = mapped_column(Text, server_default="21:00")
    gdrive_folder_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gdrive_folder_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Promotion / campaign state
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    view_target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paused_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_campaign_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    view_target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    views_total: Mapped[int] = mapped_column(Integer, server_default="0")
    posts_total: Mapped[int] = mapped_column(Integer, server_default="0")
    __table_args__ = (
        CheckConstraint("status IN ('active','ended','reset')", name="campaigns_status_chk"),
    )


class ErrorLog(Base):
    __tablename__ = "error_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    level: Mapped[str] = mapped_column(Text, server_default="error")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ArtistAccount(Base):
    __tablename__ = "artist_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tiktok_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_handle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Expanded OAuth fields (also declared on DB via _migrate_artist_oauth_columns).
    tiktok_refresh_token:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_expires_at:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_scopes:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_user_id:          Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_refresh_token:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_expires_at:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_scopes:          Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_user_id:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_expires_at:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_scopes:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_user_id:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_refresh_token:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_expires_at:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_scopes:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facebook_user_id:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Per-variation Drive folder, optional residential proxy, and per-variation
    # pause (also declared on DB via _migrate_per_variation_columns).
    gdrive_folder_url:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gdrive_folder_id:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proxy_url:               Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paused_reason:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # TikTok Direct Post per-variation settings — see
    # _migrate_per_variation_columns. The dispatcher reads these and
    # converts allow_* → disable_* at adapter call time.
    tiktok_post_as_draft:            Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_disclosure_enabled:       Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_disclose_your_brand:      Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_disclose_branded_content: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_allow_comment:            Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_allow_duet:               Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_allow_stitch:             Mapped[bool] = mapped_column(Boolean, server_default="false")
    tiktok_privacy_level:            Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_consent_at:               Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False)
    # NULL = "shared pool" (legacy artist-level clips, usable by every
    # variation). Non-NULL = scoped to one variation only.
    artist_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("artist_accounts.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gdrive_file_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    times_posted: Mapped[int] = mapped_column(Integer, server_default="0")
    last_posted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    __table_args__ = (CheckConstraint("source IN ('upload','gdrive')", name="clips_source_chk"),)


class ClipCaptionVariant(Base):
    """Per-(clip, variation, platform) paraphrased caption.

    Cached so the same clip always gets the same caption on the same
    variation+platform — repeat runs of the dispatcher post identical text,
    and platforms don't see the identical base caption across every
    variation that shares a clip.
    """
    __tablename__ = "clip_caption_variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    variation_id: Mapped[int] = mapped_column(
        ForeignKey("artist_accounts.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    source_caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    __table_args__ = (
        UniqueConstraint(
            "clip_id", "variation_id", "platform", name="clip_caption_variants_uniq"
        ),
        CheckConstraint(
            "platform IN ('tiktok','youtube','instagram','facebook')",
            name="clip_caption_variants_platform_chk",
        ),
    )


class ClipPost(Base):
    __tablename__ = "clip_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    artist_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    clip_filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artist_account_id: Mapped[int] = mapped_column(
        ForeignKey("artist_accounts.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    platform_post_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="scheduled")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, server_default="0")
    view_count_updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    # Set when the view poller detects the post is gone from the platform
    # (drop-to-zero from a non-zero count, or an explicit not-found from the
    # adapter). NULL = alive; any value = deleted on the platform.
    # Dashboard counts exclude rows where this is set.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    # Stamped True when TikTok inbox/MEDIA_UPLOAD was used (post-as-draft).
    # The view poller skips drafts (no public stats until the user
    # publishes from their inbox) and the dashboard renders a "draft"
    # pill. The migration in _migrate_tiktok_per_target_settings adds
    # this column to both clip_posts AND outputs; the model column was
    # missing here, so update_clip_post(..., posted_as_draft=...) raised
    # SQLAlchemy "Unconsumed column names: posted_as_draft" and broke
    # every Clipping dispatch.
    posted_as_draft: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Set by retry-as-draft: dispatcher uses TikTok INBOX mode for this row
    # regardless of the variation's tiktok_post_as_draft setting.
    force_inbox: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    __table_args__ = (
        CheckConstraint(
            "platform IN ('tiktok','youtube','instagram','facebook')",
            name="clip_posts_platform_chk",
        ),
        CheckConstraint(
            "status IN ('scheduled','posting','posted','failed')", name="clip_posts_status_chk"
        ),
    )


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
    if val is None:
        return val
    if isinstance(val, datetime):
        # All timestamp columns are TIMESTAMP WITHOUT TIME ZONE — asyncpg rejects
        # tz-aware datetimes against them. Normalise by converting to UTC and
        # stripping tzinfo so callers can hand us either flavour.
        if val.tzinfo is not None:
            return val.astimezone(timezone.utc).replace(tzinfo=None)
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
    # col = :name, col >= :name, col < :name, col > :name, col <= :name
    for match in re.finditer(r"(\w+)\s*(?:=|>=?|<=?|<>|!=)\s*:(\w+)", sql):
        col, name = match.group(1), match.group(2)
        if col in _TIMESTAMP_COLUMNS:
            try:
                idx = names.index(name)
                out[idx] = _parse_timestamp(out[idx])
            except (ValueError, IndexError):
                pass
    # Catch-all: strip tz from any datetime bind, regardless of column name —
    # every timestamp column in this schema is TIMESTAMP WITHOUT TIME ZONE, so
    # a tz-aware datetime binding is always wrong.
    for i, v in enumerate(out):
        if isinstance(v, datetime) and v.tzinfo is not None:
            out[i] = v.astimezone(timezone.utc).replace(tzinfo=None)
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
        if stripped.startswith("UPDATE") and "RETURNING" in stripped:
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


async def _migrate_artist_oauth_columns(conn) -> None:
    """Idempotently add OAuth-related columns to artist_accounts (Postgres)."""
    for col in OAUTH_ACCOUNT_COLUMNS:
        await conn.execute(
            text(f'ALTER TABLE artist_accounts ADD COLUMN IF NOT EXISTS {col} TEXT')
        )


async def _migrate_campaign_columns(conn) -> None:
    """Add promotion/campaign columns to artists + clip_posts (idempotent)."""
    artist_cols = [
        ("is_active", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("view_target", "INTEGER"),
        ("paused_reason", "TEXT"),
        ("current_campaign_id", "INTEGER"),
    ]
    for name, typ in artist_cols:
        await conn.execute(text(f"ALTER TABLE artists ADD COLUMN IF NOT EXISTS {name} {typ}"))

    clip_post_cols = [
        ("artist_id", "INTEGER"),
        ("campaign_id", "INTEGER"),
        ("clip_filename", "TEXT"),
        ("caption_snapshot", "TEXT"),
        # Set when the view poller detects the post is gone from the platform.
        # Dashboard counts exclude rows where this is set.
        ("deleted_at", "TIMESTAMP"),
    ]
    for name, typ in clip_post_cols:
        await conn.execute(text(f"ALTER TABLE clip_posts ADD COLUMN IF NOT EXISTS {name} {typ}"))

    # Slot-level unique index (replaces the per-clip_id one). The old index
    # let two planner ticks that picked different clips for the same
    # (account, platform, slot) both insert — producing duplicate-fire days.
    # Drop the old, create the new. IF NOT EXISTS / IF EXISTS make it idempotent.
    await conn.execute(text(
        "DROP INDEX IF EXISTS clip_posts_no_duplicate_slots"
    ))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS clip_posts_no_dup_slot "
        "ON clip_posts (artist_account_id, platform, scheduled_for) "
        "WHERE status = 'scheduled'"
    ))

    # Drop the clip_id FK so historical clip_posts can survive clip deletion
    # (post-reset). Safe to run repeatedly — the DROP CONSTRAINT IF EXISTS no-ops.
    await conn.execute(text(
        "ALTER TABLE clip_posts DROP CONSTRAINT IF EXISTS clip_posts_clip_id_fkey"
    ))
    # And relax NOT NULL on clip_id (first run only; no-op after).
    await conn.execute(text("ALTER TABLE clip_posts ALTER COLUMN clip_id DROP NOT NULL"))

    # Backfill clip_posts.artist_id from the clip (if not set yet).
    await conn.execute(text(
        "UPDATE clip_posts cp SET artist_id = c.artist_id "
        "FROM clips c WHERE cp.clip_id = c.id AND cp.artist_id IS NULL"
    ))


async def _migrate_per_platform_post_columns(conn) -> None:
    """Per-platform music + video paths on brand posts (idempotent).

    Touches only brand-side tables (posts, outputs, music_tracks). Does not
    alter anything in the clipping pipeline (artists, artist_accounts, clips,
    clip_posts) — those stay on their existing schema.
    """
    post_cols = [
        ("youtube_music_track_id", "INTEGER"),
        ("instagram_music_track_id", "INTEGER"),
        ("facebook_music_track_id", "INTEGER"),
    ]
    for name, typ in post_cols:
        await conn.execute(text(f"ALTER TABLE posts ADD COLUMN IF NOT EXISTS {name} {typ}"))

    output_cols = [
        ("youtube_video_path", "TEXT"),
        ("instagram_video_path", "TEXT"),
        ("facebook_video_path", "TEXT"),
    ]
    for name, typ in output_cols:
        await conn.execute(text(f"ALTER TABLE outputs ADD COLUMN IF NOT EXISTS {name} {typ}"))

    # music_tracks.platforms_allowed — CSV of platforms a track is cleared for.
    await conn.execute(text(
        "ALTER TABLE music_tracks ADD COLUMN IF NOT EXISTS "
        "platforms_allowed TEXT NOT NULL DEFAULT 'youtube,instagram,facebook'"
    ))


async def _migrate_per_variation_columns(conn) -> None:
    """Add per-variation GDrive + proxy + pause columns and clips.artist_account_id.

    Idempotent. After the column is added, backfills every pre-existing
    clip's artist_account_id to that artist's lowest-id variation
    (vibesofmoon, in production). New shared-pool clips stay NULL.
    """
    for col in ("gdrive_folder_url", "gdrive_folder_id", "proxy_url", "paused_reason"):
        await conn.execute(
            text(f"ALTER TABLE artist_accounts ADD COLUMN IF NOT EXISTS {col} TEXT")
        )
    await conn.execute(text(
        "ALTER TABLE clips ADD COLUMN IF NOT EXISTS artist_account_id INTEGER "
        "REFERENCES artist_accounts(id) ON DELETE SET NULL"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS clips_artist_account_idx "
        "ON clips(artist_account_id)"
    ))
    # Backfill: assign every legacy clip to its artist's first variation.
    # Per user request — they want the existing 100+ clips locked to
    # variation 1 (vibesofmoon) rather than left in the shared pool.
    await conn.execute(text(
        "UPDATE clips SET artist_account_id = ("
        "  SELECT id FROM artist_accounts "
        "  WHERE artist_id = clips.artist_id "
        "  ORDER BY id ASC LIMIT 1"
        ") "
        "WHERE artist_account_id IS NULL "
        "  AND EXISTS ("
        "    SELECT 1 FROM artist_accounts WHERE artist_id = clips.artist_id"
        "  )"
    ))

    # TikTok Direct Post API per-(post,variation) settings on `outputs`
    # (Brand pipeline) and per-variation on `artist_accounts` (Clipping
    # pipeline). All NULL / FALSE by default — TikTok requires the user
    # to actively pick privacy and disclosure on every flow, so no
    # column has a meaningful default.
    _tt_bool_cols = (
        "tiktok_post_as_draft",
        "tiktok_disclosure_enabled",
        "tiktok_disclose_your_brand",
        "tiktok_disclose_branded_content",
        "tiktok_allow_comment",
        "tiktok_allow_duet",
        "tiktok_allow_stitch",
    )
    for col in _tt_bool_cols:
        await conn.execute(text(
            f"ALTER TABLE outputs ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT FALSE"
        ))
        await conn.execute(text(
            f"ALTER TABLE artist_accounts ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT FALSE"
        ))
    for tbl in ("outputs", "artist_accounts"):
        await conn.execute(text(
            f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS tiktok_privacy_level TEXT"
        ))
        await conn.execute(text(
            f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS tiktok_consent_at TIMESTAMP"
        ))

    # Posted-as-draft flag on the per-row history. View poller skips
    # drafts (no public stats until the user publishes from their inbox)
    # and the dashboard renders a "draft" pill.
    for tbl in ("clip_posts", "outputs"):
        await conn.execute(text(
            f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS posted_as_draft BOOLEAN DEFAULT FALSE"
        ))

    # force_inbox on clip_posts: set by retry-as-draft so the dispatcher
    # uses TikTok INBOX mode for this specific row even if the variation
    # is configured for DIRECT_POST. Cleared after a successful post.
    await conn.execute(text(
        "ALTER TABLE clip_posts ADD COLUMN IF NOT EXISTS force_inbox BOOLEAN DEFAULT FALSE"
    ))

    # Per-account residential proxy on the Brand `accounts` table —
    # mirror of artist_accounts.proxy_url. Used by post_now to route
    # OAuth refresh + every adapter call through the account's
    # configured residential exit, addressing the "0 views from API
    # posts" datacenter-fingerprint suppression on US TikTok accounts.
    await conn.execute(text(
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS proxy_url TEXT"
    ))


async def _migrate_user_status_pending(conn) -> None:
    """Expand users.status CHECK to include 'pending' (added for admin-approved registration)."""
    # Drop old constraint if present, re-add expanded one. IF EXISTS makes it idempotent.
    await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_status_chk"))
    await conn.execute(text(
        "ALTER TABLE users ADD CONSTRAINT users_status_chk "
        "CHECK (status IN ('active', 'suspended', 'pending'))"
    ))


async def _migrate_email_features(conn) -> None:
    """Add email notification columns to users, reminder column to clip_posts."""
    await conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_notifications BOOLEAN DEFAULT TRUE"
    ))
    await conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS unsubscribe_token TEXT"
    ))
    await conn.execute(text(
        "ALTER TABLE clip_posts ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ"
    ))
    await conn.execute(text(
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ"
    ))
    # email_otps is a new table — handled by create_all via the ORM model.
    # Index for fast OTP lookups:
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_email_otps_email_purpose "
        "ON email_otps (email, purpose, used_at)"
    ))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_oauth_columns(conn)
        await _migrate_artist_oauth_columns(conn)
        await _migrate_campaign_columns(conn)
        await _migrate_per_platform_post_columns(conn)
        await _migrate_per_variation_columns(conn)
        await _migrate_user_status_pending(conn)
        await _migrate_email_features(conn)
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

async def create_user(db: Connection, email: str, password_hash: str, name: str, role: str = "user", status: str = "active"):
    s = db.session
    stmt = insert(User).values(email=email, password_hash=password_hash, name=name, role=role, status=status).returning(User.id)
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


async def update_music_track(db: Connection, track_id: int, **kwargs):
    s = db.session
    if kwargs:
        await s.execute(update(MusicTrack).where(MusicTrack.id == track_id).values(**_prep(kwargs)))
        await s.commit()


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


# --- Artists ---

async def create_artist(
    db: Connection,
    name: str,
    slug: str,
    user_id: int | None = None,
    timezone: str = "US/Eastern",
    posts_per_day: int = 3,
    window_start: str = "09:00",
    window_end: str = "21:00",
):
    s = db.session
    stmt = (
        insert(Artist)
        .values(
            name=name, slug=slug, user_id=user_id, timezone=timezone,
            posts_per_day=posts_per_day, window_start=window_start, window_end=window_end,
        )
        .returning(Artist.id)
    )
    aid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return aid


async def get_artists(db: Connection, user_id: int | None = None):
    s = db.session
    stmt = select(Artist)
    if user_id:
        stmt = stmt.where(Artist.user_id == user_id)
    stmt = stmt.order_by(Artist.created_at.desc())
    return _rows((await s.execute(stmt)).scalars().all())


async def get_artist(db: Connection, artist_id: int):
    s = db.session
    return _row(
        (await s.execute(select(Artist).where(Artist.id == artist_id))).scalar_one_or_none()
    )


async def get_artist_by_slug(db: Connection, user_id: int, slug: str):
    s = db.session
    return _row(
        (await s.execute(
            select(Artist).where(Artist.user_id == user_id, Artist.slug == slug)
        )).scalar_one_or_none()
    )


async def update_artist(db: Connection, artist_id: int, **kwargs):
    s = db.session
    await s.execute(update(Artist).where(Artist.id == artist_id).values(**_prep(kwargs)))
    await s.commit()


async def delete_artist(db: Connection, artist_id: int):
    s = db.session
    await s.execute(delete(Artist).where(Artist.id == artist_id))
    await s.commit()


# --- Artist accounts (variations) ---

async def create_artist_account(db: Connection, artist_id: int, name: str, **kwargs):
    s = db.session
    stmt = (
        insert(ArtistAccount)
        .values(artist_id=artist_id, name=name, **_prep(kwargs))
        .returning(ArtistAccount.id)
    )
    vid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return vid


async def get_artist_accounts(db: Connection, artist_id: int):
    s = db.session
    rows = await s.execute(
        select(ArtistAccount).where(ArtistAccount.artist_id == artist_id).order_by(ArtistAccount.id)
    )
    return _rows(rows.scalars().all())


async def get_artist_account(db: Connection, variation_id: int):
    s = db.session
    return _row(
        (
            await s.execute(select(ArtistAccount).where(ArtistAccount.id == variation_id))
        ).scalar_one_or_none()
    )


async def update_artist_account(db: Connection, variation_id: int, **kwargs):
    s = db.session
    await s.execute(
        update(ArtistAccount).where(ArtistAccount.id == variation_id).values(**_prep(kwargs))
    )
    await s.commit()


async def delete_artist_account(db: Connection, variation_id: int):
    s = db.session
    await s.execute(delete(ArtistAccount).where(ArtistAccount.id == variation_id))
    await s.commit()


# --- Clips ---

async def create_clip(
    db: Connection,
    artist_id: int,
    source: str,
    filename: str,
    local_path: str | None = None,
    gdrive_file_id: str | None = None,
    caption: str | None = None,
    duration_s: float | None = None,
    artist_account_id: int | None = None,
):
    s = db.session
    stmt = (
        insert(Clip)
        .values(
            artist_id=artist_id, source=source, filename=filename,
            local_path=local_path, gdrive_file_id=gdrive_file_id,
            caption=caption, duration_s=duration_s,
            artist_account_id=artist_account_id,
        )
        .returning(Clip.id)
    )
    cid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return cid


async def get_clips(db: Connection, artist_id: int):
    s = db.session
    rows = await s.execute(
        select(Clip).where(Clip.artist_id == artist_id).order_by(Clip.created_at.desc())
    )
    return _rows(rows.scalars().all())


async def get_clip(db: Connection, clip_id: int):
    s = db.session
    return _row((await s.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none())


async def update_clip(db: Connection, clip_id: int, **kwargs):
    s = db.session
    await s.execute(update(Clip).where(Clip.id == clip_id).values(**_prep(kwargs)))
    await s.commit()


async def delete_clip(db: Connection, clip_id: int):
    s = db.session
    await s.execute(delete(Clip).where(Clip.id == clip_id))
    await s.commit()


# --- Clip caption variants ---

async def get_clip_caption_variant(
    db: Connection, clip_id: int, variation_id: int, platform: str
):
    s = db.session
    return _row(
        (
            await s.execute(
                select(ClipCaptionVariant).where(
                    ClipCaptionVariant.clip_id == clip_id,
                    ClipCaptionVariant.variation_id == variation_id,
                    ClipCaptionVariant.platform == platform,
                )
            )
        ).scalar_one_or_none()
    )


async def upsert_clip_caption_variant(
    db: Connection, clip_id: int, variation_id: int, platform: str,
    caption: str, source_caption: str,
):
    s = db.session
    existing = (
        await s.execute(
            select(ClipCaptionVariant).where(
                ClipCaptionVariant.clip_id == clip_id,
                ClipCaptionVariant.variation_id == variation_id,
                ClipCaptionVariant.platform == platform,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.caption = caption
        existing.source_caption = source_caption
        await s.commit()
        return existing.id
    row = ClipCaptionVariant(
        clip_id=clip_id, variation_id=variation_id, platform=platform,
        caption=caption, source_caption=source_caption,
    )
    s.add(row)
    await s.commit()
    return row.id


async def delete_clip_caption_variants(db: Connection, clip_id: int):
    s = db.session
    await s.execute(
        delete(ClipCaptionVariant).where(ClipCaptionVariant.clip_id == clip_id)
    )
    await s.commit()


# --- Clip posts ---

async def create_clip_post(
    db: Connection,
    clip_id: int | None,
    artist_account_id: int,
    platform: str,
    scheduled_for: datetime | str | None = None,
    status: str = "scheduled",
    artist_id: int | None = None,
    campaign_id: int | None = None,
    clip_filename: str | None = None,
    caption_snapshot: str | None = None,
):
    s = db.session
    # Guard against the multi-worker race in plan_slots_once: if two workers
    # both decide today's slots aren't materialised, both insert the same
    # (artist_account_id, platform, scheduled_for, clip_id) row. The partial
    # unique index `clip_posts_no_duplicate_slots` makes the second insert a
    # silent no-op via ON CONFLICT so we don't double-post.
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = (
        pg_insert(ClipPost)
        .values(
            clip_id=clip_id,
            artist_account_id=artist_account_id,
            platform=platform,
            scheduled_for=_parse_timestamp(scheduled_for),
            status=status,
            artist_id=artist_id,
            campaign_id=campaign_id,
            clip_filename=clip_filename,
            caption_snapshot=caption_snapshot,
        )
        .on_conflict_do_nothing(
            # Match the slot-level unique index. Including clip_id in the
            # conflict key (the old behaviour) meant two planner ticks that
            # picked DIFFERENT clips for the same (account, platform, slot)
            # both inserted, producing the duplicate-fire chaos. Slot-level
            # is the right granularity: at most one scheduled row per
            # (account, platform, scheduled_for), period.
            index_elements=["artist_account_id", "platform", "scheduled_for"],
            index_where=text("status = 'scheduled'"),
        )
        .returning(ClipPost.id)
    )
    pid = (await s.execute(stmt)).scalar_one_or_none()
    await s.commit()
    return pid


# --- Campaigns ---

async def create_campaign(db: Connection, artist_id: int, name: str, view_target: int | None):
    s = db.session
    stmt = (
        insert(Campaign)
        .values(artist_id=artist_id, name=name, view_target=view_target, status="active")
        .returning(Campaign.id)
    )
    cid = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return cid


async def get_campaign(db: Connection, campaign_id: int):
    s = db.session
    return _row(
        (await s.execute(select(Campaign).where(Campaign.id == campaign_id))).scalar_one_or_none()
    )


async def get_campaigns(db: Connection, artist_id: int):
    s = db.session
    rows = await s.execute(
        select(Campaign).where(Campaign.artist_id == artist_id).order_by(Campaign.started_at.desc())
    )
    return _rows(rows.scalars().all())


async def update_campaign(db: Connection, campaign_id: int, **kwargs):
    s = db.session
    await s.execute(update(Campaign).where(Campaign.id == campaign_id).values(**_prep(kwargs)))
    await s.commit()


# --- Error logs ---

async def log_error(
    db: Connection,
    source: str,
    message: str,
    traceback: str | None = None,
    user_id: int | None = None,
    context: str | None = None,
    level: str = "error",
):
    """Append a row to error_logs. Best-effort — swallows its own failures so
    the caller's error path is never aggravated by a logging problem."""
    try:
        s = db.session
        stmt = insert(ErrorLog).values(
            source=source, message=message[:8000],
            traceback=(traceback or "")[:16000] or None,
            user_id=user_id, context=context, level=level,
        )
        await s.execute(stmt)
        await s.commit()
    except Exception:
        pass


async def get_error_logs(db: Connection, limit: int = 200, source: str | None = None):
    s = db.session
    q = select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(limit)
    if source:
        q = q.where(ErrorLog.source == source)
    rows = await s.execute(q)
    return _rows(rows.scalars().all())


async def delete_old_error_logs(db: Connection, keep_last: int = 1000):
    """Trim error_logs to the most recent N rows."""
    s = db.session
    sub = select(ErrorLog.id).order_by(ErrorLog.created_at.desc()).limit(keep_last).subquery()
    await s.execute(delete(ErrorLog).where(~ErrorLog.id.in_(select(sub))))
    await s.commit()


async def get_clip_posts(
    db: Connection,
    artist_id: int | None = None,
    clip_id: int | None = None,
    status: str | None = None,
    limit: int | None = None,
):
    s = db.session
    stmt = select(ClipPost)
    if artist_id:
        # Filter by clip_posts.artist_id directly. Don't join to Clip — an
        # inner join silently drops historical rows whose clip_id points
        # at a deleted clip (the FK was intentionally removed so post
        # history survives directory cleanup, but an inner join undoes
        # that). Migration backfilled clip_posts.artist_id, and
        # create_clip_post sets it on insert, so this column is reliable.
        stmt = stmt.where(ClipPost.artist_id == artist_id)
    if clip_id:
        stmt = stmt.where(ClipPost.clip_id == clip_id)
    if status:
        stmt = stmt.where(ClipPost.status == status)
    stmt = stmt.order_by(ClipPost.scheduled_for.desc().nullslast(), ClipPost.id.desc())
    if limit:
        stmt = stmt.limit(limit)
    rows = await s.execute(stmt)
    return _rows(rows.scalars().all())


async def update_clip_post(db: Connection, clip_post_id: int, **kwargs):
    s = db.session
    await s.execute(update(ClipPost).where(ClipPost.id == clip_post_id).values(**_prep(kwargs)))
    await s.commit()
