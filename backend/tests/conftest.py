"""Shared pytest fixtures for the Kopis backend test suite.

These tests hit a REAL PostgreSQL database — not sqlite, not mocks. The
whole point of the concurrency tests in test_execution_locking.py is to
prove that a database-level conditional UPDATE serializes concurrent
callers; that guarantee only means something if it's exercised against the
actual database engine the app runs on (Postgres) and through the actual
async driver it uses (asyncpg), via genuinely separate connections/sessions
— which is what two asyncio tasks each opening their own AsyncSession give
you here.

Getting a Postgres to point these tests at
--------------------------------------------------------------------------
Point them at any disposable Postgres 16 via the same POSTGRES_* env vars
config.py already reads, e.g.:

    docker run -d --name kopis-test-pg \
        -e POSTGRES_DB=kopis_test -e POSTGRES_USER=kopis \
        -e POSTGRES_PASSWORD=kopistest -p 55432:5432 postgres:16-alpine

    cd backend
    POSTGRES_HOST=localhost POSTGRES_PORT=55432 POSTGRES_DB=kopis_test \
        POSTGRES_USER=kopis POSTGRES_PASSWORD=kopistest \
        python -m alembic upgrade head   # once, to create the schema

    POSTGRES_HOST=localhost POSTGRES_PORT=55432 POSTGRES_DB=kopis_test \
        POSTGRES_USER=kopis POSTGRES_PASSWORD=kopistest \
        pytest

If POSTGRES_* env vars aren't already set, the defaults below point at
exactly that container/DB, so plain `pytest` works once it exists and has
had `alembic upgrade head` run against it. These tests never touch the
dev/prod database defined in `.env` — they only look at real environment
variables, and .env is not loaded here.

Do NOT point this at a database you care about: table-clearing fixtures
below delete all rows from the tables involved on every test.
"""

import os
import sys
import uuid
from pathlib import Path

# Point at a disposable local test database unless the caller already set
# these (e.g. CI, or a different sandbox instance). Must happen BEFORE any
# import of `config`/`db.*`, since Settings() is instantiated at import time.
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "55432")
os.environ.setdefault("POSTGRES_DB", "kopis_test")
os.environ.setdefault("POSTGRES_USER", "kopis")
os.environ.setdefault("POSTGRES_PASSWORD", "kopistest")

# backend/ is the import root for bare `from config import ...` /
# `from db.tables import ...` style imports used throughout this codebase
# (see db/migrations/env.py for the same pattern) — make sure it's on
# sys.path regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.tables import Approval, Device, Finding, Recommendation

# Tables truncated between tests, in FK-safe order (children first).
_TABLES_TO_CLEAR = ["approvals", "recommendations", "findings", "snapshots", "devices"]


@pytest_asyncio.fixture
async def engine():
    # Function-scoped (not session-scoped) deliberately: pytest-asyncio
    # gives each test function its own event loop by default, and an
    # asyncpg connection pool created on one loop breaks if reused from
    # another. Recreating the engine per test keeps every asyncpg
    # connection bound to the loop it was actually opened on.
    eng = create_async_engine(settings.database_url, echo=False)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_db(session_factory):
    """Truncate all tables this suite touches before AND after each test.

    Each test gets its own genuinely separate AsyncSession/connections (see
    below) rather than a shared outer transaction, precisely because the
    concurrency tests need real, independent connections racing against
    each other — a shared-transaction-with-rollback isolation trick would
    hide them from each other and defeat the point. Truncation is the
    isolation mechanism instead.
    """
    async with session_factory() as db:
        for table in _TABLES_TO_CLEAR:
            await db.execute(_text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        await db.commit()
    yield
    async with session_factory() as db:
        for table in _TABLES_TO_CLEAR:
            await db.execute(_text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        await db.commit()


def _text(sql: str):
    from sqlalchemy import text
    return text(sql)


@pytest_asyncio.fixture
async def db(session_factory):
    """A single AsyncSession — use for setup/assertions in a test.

    For concurrency tests that need two independent DB connections racing
    each other, open additional sessions directly from `session_factory`
    rather than reusing this one.
    """
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def make_approval(db):
    """Factory fixture: build a Device -> Snapshot -> Finding -> Recommendation
    -> Approval chain and return the approval id.

    Usage: approval_id = await make_approval(status="approved")
    """

    async def _make(status: str = "pending", commands: list | None = None, jira_issue_key: str | None = None):
        suffix = uuid.uuid4().hex[:8]
        device = Device(
            hostname=f"test-router-{suffix}",
            management_ip="10.0.0.1",
            platform="iosxe",
            device_type="router",
        )
        db.add(device)
        await db.flush()

        from db.tables import Snapshot

        snapshot = Snapshot(
            device_id=device.id,
            snapshot_data={"interface": {}},
            triggered_by="test",
        )
        db.add(snapshot)
        await db.flush()

        finding = Finding(
            snapshot_id=snapshot.id,
            device_id=device.id,
            category="interface",
            severity="high",
            confidence=0.9,
            title="Interface GigabitEthernet0/1 is admin-down",
            description="test finding",
            affected_entity="GigabitEthernet0/1",
            requires_remediation=True,
        )
        db.add(finding)
        await db.flush()

        rec = Recommendation(
            finding_id=finding.id,
            action_description="Re-enable interface",
            commands=commands if commands is not None else [{"command": "no shutdown"}],
            risk_level="low",
            reasoning="test reasoning",
        )
        db.add(rec)
        await db.flush()

        approval = Approval(
            recommendation_id=rec.id,
            status=status,
            jira_issue_key=jira_issue_key,
        )
        db.add(approval)
        await db.commit()
        return approval.id

    return _make
