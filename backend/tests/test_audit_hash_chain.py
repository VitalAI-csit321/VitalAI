"""Prove the hash-chain trigger computes real, linked SHA-256 hashes.

Same Postgres-only skip pattern as tests/test_audit_trigger.py - these
require the real pgcrypto-backed trigger and cannot run on SQLite.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import hash_password
from app.models import IntakeCase, IntakeStatus, User, UserRole
from app.services.audit_service import record_event

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL") or os.environ.get(
    "DATABASE_URL" if "postgresql" in (os.environ.get("DATABASE_URL", "")) else "_skip_"
)

_needs_postgres = pytest.mark.skipif(
    not POSTGRES_TEST_URL or "postgresql" not in POSTGRES_TEST_URL,
    reason="POSTGRES_TEST_URL not set or not a PostgreSQL URL, skipping trigger tests",
)


@pytest_asyncio.fixture
async def pg_engine(test_engine):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("No Postgres URL, skipping trigger tests")
    yield test_engine


@pytest_asyncio.fixture
async def pg_session(pg_engine):
    session_factory = async_sessionmaker(
        bind=pg_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def chain_actor(pg_session: AsyncSession) -> User:
    user = User(
        email=f"chain-tester-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        full_name="Chain Tester",
        role=UserRole.ADMIN,
    )
    pg_session.add(user)
    await pg_session.flush()
    return user


@pytest_asyncio.fixture
async def chain_case(pg_session: AsyncSession) -> IntakeCase:
    case = IntakeCase(
        patient_name="Chain Patient",
        contact_reason="test",
        contact_channel="phone",
        status=IntakeStatus.RECEIVED,
    )
    pg_session.add(case)
    await pg_session.flush()
    return case


def _expected_hash(prev_hash: str | None, row) -> str:
    canonical = "|".join(
        [
            str(row.case_id) if row.case_id else "",
            str(row.actor_id) if row.actor_id else "",
            row.actor_label or "",
            row.action,
            json.dumps(row.details),
            row.timestamp.isoformat(),
        ]
    )
    return hashlib.sha256(((prev_hash or "") + canonical).encode()).hexdigest()


@_needs_postgres
async def test_insert_computes_event_hash(
    pg_session: AsyncSession, chain_case: IntakeCase, chain_actor: User
):
    """A freshly inserted event must get a non-null event_hash from the trigger."""
    event = await record_event(
        pg_session,
        case_id=chain_case.id,
        actor=chain_actor,
        action="test.chain_check",
        details={"purpose": "hash chain test"},
    )
    await pg_session.commit()
    await pg_session.refresh(event)

    assert event.event_hash is not None
    assert len(event.event_hash) == 64


@_needs_postgres
async def test_chain_links_predecessor_hash(
    pg_session: AsyncSession, chain_case: IntakeCase, chain_actor: User
):
    """The second event's predecessor_hash must equal the first event's event_hash."""
    first = await record_event(
        pg_session,
        case_id=chain_case.id,
        actor=chain_actor,
        action="test.chain_first",
        details={},
    )
    await pg_session.commit()
    await pg_session.refresh(first)

    second = await record_event(
        pg_session,
        case_id=chain_case.id,
        actor=chain_actor,
        action="test.chain_second",
        details={},
    )
    await pg_session.commit()
    await pg_session.refresh(second)

    assert second.predecessor_hash == first.event_hash
    assert second.event_hash != first.event_hash


@_needs_postgres
async def test_verify_chain_reports_valid_when_untampered(
    pg_session: AsyncSession, chain_case: IntakeCase, chain_actor: User
):
    for label in ("one", "two", "three"):
        await record_event(
            pg_session,
            case_id=chain_case.id,
            actor=chain_actor,
            action=f"test.chain_verify_{label}",
            details={"label": label},
        )
        await pg_session.commit()

    result = await pg_session.execute(text("SELECT valid, checked_count FROM verify_audit_chain()"))
    row = result.one()
    assert row.valid is True
    assert row.checked_count >= 3


@_needs_postgres
async def test_verify_chain_detects_tampering(
    pg_session: AsyncSession, chain_case: IntakeCase, chain_actor: User
):
    """A hash corrupted via a privileged bypass of the append-only trigger
    must be detected. Normal INSERT/UPDATE paths cannot produce this state
    at all (INSERT's hash is always overwritten by the trigger; UPDATE is
    blocked outright), the disable/enable dance below simulates the only
    way a real tamper could ever happen: a privileged, out-of-band write.

    Everything from the disable-trigger step onward runs in one
    uncommitted transaction, then rolls back. verify_audit_chain() still
    sees the corruption while it's live (same session, same transaction),
    but nothing survives afterward - audit_events is undeletable/
    unupdatable through the normal app, so a committed corruption here
    would permanently break every future chain check against this shared
    database, not just this test run.
    """
    event = await record_event(
        pg_session,
        case_id=chain_case.id,
        actor=chain_actor,
        action="test.chain_tamper_target",
        details={},
    )
    await pg_session.commit()
    event_id = event.id

    await pg_session.execute(
        text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update")
    )
    await pg_session.execute(
        text("UPDATE audit_events SET event_hash = 'deadbeef' WHERE id = :id"),
        {"id": event_id},
    )
    await pg_session.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update"))

    result = await pg_session.execute(
        text("SELECT valid, first_break_event_id FROM verify_audit_chain()")
    )
    row = result.one()

    await pg_session.rollback()

    assert row.valid is False
    assert str(row.first_break_event_id) == str(event_id)


@_needs_postgres
async def test_action_shape_constraint_rejects_bad_action(pg_session: AsyncSession):
    with pytest.raises(Exception, match="ck_audit_events_action_shape|violates check constraint"):
        await pg_session.execute(
            text(
                "INSERT INTO audit_events (id, actor_label, action, details, timestamp) "
                "VALUES (gen_random_uuid(), 'system', 'NOT-VALID-SHAPE', '{}'::jsonb, now())"
            )
        )
        await pg_session.flush()


@_needs_postgres
async def test_verify_chain_survives_out_of_order_timestamps(
    pg_session: AsyncSession, chain_case: IntakeCase, chain_actor: User
):
    """The chain must link by true insert order (sequence_number), not by the
    client-assigned `timestamp` column, since the two can diverge under
    concurrent writers.

    Regression test for a real bug found on the shared dev DB: the old
    trigger picked its "predecessor" via `ORDER BY timestamp DESC, id DESC`,
    so a row inserted first but stamped with a *later* timestamp than a row
    inserted after it would corrupt the chain's logical shape (confirmed via
    a stored predecessor_hash pointing at a row timestamped after it).
    Reproduces that exact ordering here directly via raw SQL, which lets the
    two inserts specify timestamps independent of real insert order.
    """
    later_ts = datetime.now(UTC) + timedelta(seconds=5)
    earlier_ts = datetime.now(UTC) - timedelta(seconds=5)

    # Inserted FIRST but stamped with the LATER timestamp.
    await pg_session.execute(
        text(
            "INSERT INTO audit_events (id, case_id, actor_id, actor_label, action, details, timestamp) "
            "VALUES (gen_random_uuid(), :case_id, :actor_id, 'system', 'test.race_later_ts_first', '{}'::jsonb, :ts)"
        ),
        {"case_id": chain_case.id, "actor_id": chain_actor.id, "ts": later_ts},
    )
    # Inserted SECOND but stamped with the EARLIER timestamp.
    await pg_session.execute(
        text(
            "INSERT INTO audit_events (id, case_id, actor_id, actor_label, action, details, timestamp) "
            "VALUES (gen_random_uuid(), :case_id, :actor_id, 'system', 'test.race_earlier_ts_second', '{}'::jsonb, :ts)"
        ),
        {"case_id": chain_case.id, "actor_id": chain_actor.id, "ts": earlier_ts},
    )
    await pg_session.commit()

    result = await pg_session.execute(
        text("SELECT valid, first_break_event_id FROM verify_audit_chain()")
    )
    row = result.one()
    assert row.valid is True, f"chain broke at {row.first_break_event_id}"
