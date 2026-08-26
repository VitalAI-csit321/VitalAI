"""Overlap constraint tests. Postgres-only by necessity.

EXCLUDE USING gist has no SQLite equivalent, so these use the pg_session
fixture. On SQLite they would pass without exercising anything, which is
worse than not having them.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.appointment import Appointment, AppointmentStatus

pytestmark = pytest.mark.asyncio

_BASE = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


async def _add(pg_session, doctor_id, case_id, start, minutes, status, code):
    appointment = Appointment(
        doctor_id=doctor_id,
        case_id=case_id,
        time_slot=start,
        duration_minutes=minutes,
        status=status,
        reference_code=code,
    )
    pg_session.add(appointment)
    await pg_session.flush()
    return appointment


async def test_overlapping_confirmed_appointments_are_rejected(pg_appointment_fixture):
    session, doctor_id, case_id = pg_appointment_fixture
    await _add(session, doctor_id, case_id, _BASE, 60, AppointmentStatus.CONFIRMED, "APT-AAA001")
    with pytest.raises(IntegrityError):
        await _add(
            session,
            doctor_id,
            case_id,
            _BASE + timedelta(minutes=30),
            30,
            AppointmentStatus.CONFIRMED,
            "APT-AAA002",
        )


async def test_adjacent_appointments_are_allowed(pg_appointment_fixture):
    session, doctor_id, case_id = pg_appointment_fixture
    await _add(session, doctor_id, case_id, _BASE, 30, AppointmentStatus.CONFIRMED, "APT-BBB001")
    # Half-open range: 09:00-09:30 and 09:30-10:00 do not overlap.
    await _add(
        session,
        doctor_id,
        case_id,
        _BASE + timedelta(minutes=30),
        30,
        AppointmentStatus.CONFIRMED,
        "APT-BBB002",
    )


async def test_cancelled_appointment_releases_its_slot(pg_appointment_fixture):
    session, doctor_id, case_id = pg_appointment_fixture
    await _add(session, doctor_id, case_id, _BASE, 30, AppointmentStatus.CANCELLED, "APT-CCC001")
    await _add(session, doctor_id, case_id, _BASE, 30, AppointmentStatus.CONFIRMED, "APT-CCC002")


async def test_completed_appointment_still_reserves_its_slot(pg_appointment_fixture):
    session, doctor_id, case_id = pg_appointment_fixture
    await _add(session, doctor_id, case_id, _BASE, 30, AppointmentStatus.COMPLETED, "APT-DDD001")
    with pytest.raises(IntegrityError):
        await _add(
            session, doctor_id, case_id, _BASE, 30, AppointmentStatus.CONFIRMED, "APT-DDD002"
        )


async def test_two_pending_suggestions_may_share_one_slot(pg_appointment_fixture):
    """ADR-003: suggestions are advisory and must not reserve the slot."""
    session, doctor_id, case_id = pg_appointment_fixture
    await _add(session, doctor_id, case_id, _BASE, 30, AppointmentStatus.PENDING, "APT-EEE001")
    await _add(session, doctor_id, case_id, _BASE, 30, AppointmentStatus.PENDING, "APT-EEE002")


async def test_confirming_the_second_suggestion_conflicts(pg_appointment_fixture):
    """ADR-003: contention resolves at accept time, surfacing as a 409."""
    session, doctor_id, case_id = pg_appointment_fixture
    first = await _add(
        session, doctor_id, case_id, _BASE, 30, AppointmentStatus.PENDING, "APT-FFF001"
    )
    second = await _add(
        session, doctor_id, case_id, _BASE, 30, AppointmentStatus.PENDING, "APT-FFF002"
    )
    first.status = AppointmentStatus.CONFIRMED
    await session.flush()
    second.status = AppointmentStatus.CONFIRMED
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_zero_duration_is_rejected_by_the_check_constraint(pg_appointment_fixture):
    """F4: a zero-length range overlaps nothing and would bypass the constraint."""
    session, doctor_id, case_id = pg_appointment_fixture
    with pytest.raises(IntegrityError):
        await _add(session, doctor_id, case_id, _BASE, 0, AppointmentStatus.CONFIRMED, "APT-GGG001")


async def test_negative_duration_is_rejected(pg_appointment_fixture):
    """F5: raises DataError, not IntegrityError, without the CHECK."""
    session, doctor_id, case_id = pg_appointment_fixture
    with pytest.raises((IntegrityError, DBAPIError)):
        await _add(
            session, doctor_id, case_id, _BASE, -30, AppointmentStatus.CONFIRMED, "APT-HHH001"
        )
