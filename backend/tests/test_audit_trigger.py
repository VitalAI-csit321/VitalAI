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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import hash_password
from app.models import Base, IntakeCase, IntakeStatus, User, UserRole
from app.services.audit_service import record_event

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL") or os.environ.get(
    "DATABASE_URL" if "postgresql" in (os.environ.get("DATABASE_URL", "")) else "_skip_"
)

_needs_postgres = pytest.mark.skipif(
    not POSTGRES_TEST_URL or "postgresql" not in POSTGRES_TEST_URL,
    reason="POSTGRES_TEST_URL not set or not a PostgreSQL URL — skipping trigger tests",
)


# ---------------------------------------------------------------------------
# Fixtures — a separate engine/session that talks to Postgres
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pg_engine():
    if not POSTGRES_TEST_URL or "postgresql" not in POSTGRES_TEST_URL:
        pytest.skip("No Postgres URL — skipping trigger tests")

    engine = create_async_engine(POSTGRES_TEST_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # The append-only audit trigger lives in an Alembic migration
        # (alembic/versions/0001_initial.py), not in the models, so
        # create_all above does not create it. Recreate it here.
        await conn.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION block_audit_modification()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'audit_events is append-only — % is not permitted', TG_OP;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER audit_events_no_update
                BEFORE UPDATE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION block_audit_modification();
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER audit_events_no_delete
                BEFORE DELETE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION block_audit_modification();
                """
            )
        )
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


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
