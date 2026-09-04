"""Test fixtures for the outreach pipeline.

The suite talks to a real Postgres — the queue's guarantees live in
`FOR UPDATE SKIP LOCKED`, partial unique indexes and `ON CONFLICT`, none of
which a stub could exercise honestly. Point it at a throwaway database:

    createdb icreateflow_test
    export ICREATE_TEST_DB_DSN=postgresql+asyncpg://postgres@127.0.0.1:5432/icreateflow_test
    cd backend && python3 -m pytest

Without a reachable database the DB-backed tests skip (with the reason
printed); the pure-logic tests — templates, CSV parsing, mock driver —
still run.

No test touches a browser: every send goes through `MockMessenger`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

TEST_DSN = os.environ.get(
    "ICREATE_TEST_DB_DSN",
    "postgresql+asyncpg://postgres@127.0.0.1:5432/icreateflow_test",
)
# `database` reads this at import time, so it must be set before the import.
os.environ["ICREATE_DB_DSN"] = TEST_DSN
os.environ.setdefault("ICREATE_JWT_SECRET", "test-secret-not-used-in-production")

import database as db  # noqa: E402

#: Wiped between tests, children first.
OUTREACH_TABLES = (
    "outreach_jobs",
    "outreach_campaign_accounts",
    "outreach_targets",
    "outreach_audit_logs",
    "outreach_campaigns",
    "outreach_sending_accounts",
    "outreach_templates",
)


#: None = not tried yet, True/False = the answer from the first attempt.
_SCHEMA_READY: bool | None = None


@pytest.fixture
async def schema():
    """Create the schema once per run; skip the DB tests if there is none.

    Function-scoped on purpose — a session-scoped async fixture would need
    its own event loop scope, and `init_db` is a no-op after the first
    call, so the cost is a single boolean check.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY is None:
        try:
            await db.init_db()
            _SCHEMA_READY = True
        except Exception:  # noqa: BLE001 — any connection problem means "skip"
            _SCHEMA_READY = False
    if not _SCHEMA_READY:
        pytest.skip(
            f"No Postgres at {TEST_DSN} — set ICREATE_TEST_DB_DSN to run the "
            "database-backed outreach tests"
        )
    return True


@pytest.fixture
async def database(schema):
    """A clean Connection with the outreach tables empty."""
    conn = await db.get_db()
    from sqlalchemy import text

    await conn.session.execute(
        text(f"TRUNCATE {', '.join(OUTREACH_TABLES)} RESTART IDENTITY CASCADE")
    )
    await conn.session.commit()
    try:
        yield conn
    finally:
        await conn.close()
        # pytest-asyncio gives each test its own event loop, and pooled
        # asyncpg connections are bound to the loop that opened them.
        # Disposing here keeps the next test from inheriting a connection
        # attached to a closed loop.
        await db.engine.dispose()


@pytest.fixture
async def user(database):
    """A non-admin user that owns the campaigns and accounts under test."""
    from services.auth import hash_password

    existing = await db.get_user_by_email(database, "outreach-tests@example.com")
    if existing:
        return dict(existing)
    user_id = await db.create_user(
        database, "outreach-tests@example.com", hash_password("x" * 12), "Outreach Tester"
    )
    return dict(await db.get_user(database, user_id))


@pytest.fixture
async def settings(database):
    """Default settings with the throttles turned off.

    The send cooldown and retry backoff exist to pace real traffic; leaving
    them on would make every test sleep.
    """
    from services.outreach import config as cfg

    values = await cfg.get_all(database)
    values["outreach_min_send_interval_seconds"] = 0
    values["outreach_retry_backoff_seconds"] = 5
    return values


@pytest.fixture
async def campaign_factory(database, user):
    from services.outreach.constants import CAMPAIGN_DRAFT

    async def _make(
        name: str = "Test campaign",
        message: str = "Hello {{username}}, quick question.",
        **kwargs,
    ) -> dict:
        campaign_id = await db.create_outreach_campaign(
            database, user_id=user["id"], name=name,
            message_template=message, platform="tiktok",
            status=kwargs.pop("status", CAMPAIGN_DRAFT), **kwargs,
        )
        return dict(await db.get_outreach_campaign(database, campaign_id))

    return _make


@pytest.fixture
async def account_factory(database, user):
    from services.outreach.constants import ACCOUNT_IDLE
    from services.outreach.crypto import encrypt_session

    async def _make(name: str = "Sender 1", with_session: bool = True, **kwargs) -> dict:
        account_id = await db.create_sending_account(
            database, user_id=user["id"], name=name,
            platform=kwargs.pop("platform", "tiktok"),
            status=kwargs.pop("status", ACCOUNT_IDLE),
            enabled=kwargs.pop("enabled", True),
            session_state_encrypted=(
                encrypt_session('{"cookies": [], "origins": []}') if with_session else None
            ),
            session_reference=f"session/{name}",
            **kwargs,
        )
        return dict(await db.get_sending_account(database, account_id))

    return _make


@pytest.fixture
async def seeded(database, campaign_factory, account_factory, settings):
    """A running campaign with 3 targets and one enabled sending account."""
    from services.outreach import importer, queue as job_queue

    campaign = await campaign_factory()
    account = await account_factory()
    await importer.import_targets(
        database, campaign["id"],
        "username,profile_url\nalice,\nbob,\ncarol,\n",
    )
    await job_queue.start_campaign(database, campaign, settings)
    campaign = dict(await db.get_outreach_campaign(database, campaign["id"]))
    return {"campaign": campaign, "account": account, "settings": settings}
