"""Prove that the append-only audit trigger blocks UPDATE and DELETE.

These tests require a real PostgreSQL database with the schema applied (the
block_audit_modification trigger is Postgres-only and cannot run on SQLite).
They are skipped automatically when no Postgres URL is present, so the
default SQLite-based CI path is unaffected.  CI provides a Postgres service
container and sets POSTGRES_TEST_URL, so the tests execute there.

Run locally with:
    POSTGRES_TEST_URL=postgresql+asyncpg://... pytest tests/test_audit_trigger.py
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import hash_password
from app.models import IntakeCase, IntakeStatus, User, UserRole
from app.services.audit_service import record_event

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL") or os.environ.get(
    "DATABASE_URL" if "postgresql" in (os.environ.get("DATABASE_URL", "")) else "_skip_"
)

_needs_postgres = pytest.mark.skipif(
    not POSTGRES_TEST_URL or "postgresql" not in POSTGRES_TEST_URL,
    reason="POSTGRES_TEST_URL not set or not a PostgreSQL URL — skipping trigger tests",
)


# ---------------------------------------------------------------------------
# Fixtures — these reuse conftest.py's test_engine rather than standing up a
# second engine against the same physical database. test_engine now builds
# the Postgres schema by running Alembic migrations to head (see
# conftest.py), which is the same migration chain that installs
# audit_events_no_update/_no_delete in production — so the trigger under
# test here is never a hand-copied stand-in that can drift from migration
# 0001. With only one fixture building/tearing down schema per test, there
# is nothing left for these tests and the rest of the suite to race over,
# and it no longer matters whether CI's separate "Run migrations" step ran
# first: Alembic's upgrade-to-head is idempotent either way.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pg_engine(test_engine):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("No Postgres URL — skipping trigger tests")
    yield test_engine


@pytest_asyncio.fixture
async def pg_session(pg_engine):
    session_factory = async_sessionmaker(
        bind=pg_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def audit_actor(pg_session: AsyncSession) -> User:
    """Insert a minimal user so audit events have a valid actor_id FK.

    Uses a UUID-suffixed email so repeated runs against the same Postgres
    DB don't hit the unique constraint on users.email.
    """
    user = User(
        email=f"trigger-tester-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        full_name="Trigger Tester",
        role=UserRole.ADMIN,
    )
    pg_session.add(user)
    await pg_session.flush()
    return user


@pytest_asyncio.fixture
async def audit_case(pg_session: AsyncSession, audit_actor: User) -> IntakeCase:
    """Insert a minimal intake case so audit events have a valid case_id FK."""
    case = IntakeCase(
        patient_name="Trigger Patient",
        contact_reason="test",
        contact_channel="phone",
        status=IntakeStatus.RECEIVED,
    )
    pg_session.add(case)
    await pg_session.flush()
    return case


@pytest_asyncio.fixture
async def committed_audit_event(pg_session: AsyncSession, audit_case, audit_actor):
    """Create and commit one real audit event, then return its id."""
    event = await record_event(
        pg_session,
        case_id=audit_case.id,
        actor=audit_actor,
        action="test.trigger_check",
        details={"purpose": "trigger guard test"},
    )
    await pg_session.commit()
    return event.id


# ---------------------------------------------------------------------------
# Trigger tests
# ---------------------------------------------------------------------------


@_needs_postgres
async def test_audit_trigger_blocks_update(pg_session: AsyncSession, committed_audit_event):
    """UPDATE on audit_events must raise a database exception."""
    event_id = committed_audit_event
    with pytest.raises(DBAPIError, match="audit_events is append-only"):
        await pg_session.execute(
            text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
            {"id": event_id},
        )
        await pg_session.flush()


@_needs_postgres
async def test_audit_trigger_blocks_delete(pg_session: AsyncSession, committed_audit_event):
    """DELETE on audit_events must raise a database exception."""
    event_id = committed_audit_event
    with pytest.raises(DBAPIError, match="audit_events is append-only"):
        await pg_session.execute(
            text("DELETE FROM audit_events WHERE id = :id"),
            {"id": event_id},
        )
        await pg_session.flush()


@_needs_postgres
async def test_audit_trigger_allows_insert(pg_session: AsyncSession, audit_case, audit_actor):
    """INSERT on audit_events must succeed — the trigger must not block appends."""
    event = await record_event(
        pg_session,
        case_id=audit_case.id,
        actor=audit_actor,
        action="test.allowed_insert",
        details={"check": "insert allowed"},
    )
    await pg_session.commit()
    assert event.id is not None
