from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import AppointmentStatus
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.user import User, UserRole
from app.services import appointment_service
from app.services.appointment_service import (
    AppointmentStateError,
    CaseNotFoundError,
    DoctorNotFoundError,
    NotADoctorError,
    SlotTakenError,
)


def _user(role: UserRole) -> User:
    return User(
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        hashed_password="h",
        full_name="X",
        role=role,
    )


async def _case(db_session: AsyncSession) -> IntakeCase:
    case = IntakeCase(contact_reason="Checkup", contact_channel="phone")
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)
    return case


def _slot(offset_days: int = 1) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=offset_days)


async def test_book_appointment_creates_confirmed_and_audits(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case = await _case(db_session)
    slot = _slot()

    appointment = await appointment_service.book_appointment(
        db_session, doctor.id, case.id, slot, admin
    )

    assert appointment.doctor_id == doctor.id
    assert appointment.case_id == case.id
    assert appointment.status == AppointmentStatus.CONFIRMED

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "appointment.booked", AuditEvent.case_id == case.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].details["doctor_id"] == str(doctor.id)


async def test_book_appointment_missing_doctor_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    case = await _case(db_session)

    with pytest.raises(DoctorNotFoundError):
        await appointment_service.book_appointment(db_session, uuid4(), case.id, _slot(), admin)


async def test_book_appointment_non_doctor_role_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    front_desk = _user(UserRole.FRONT_DESK)
    db_session.add_all([admin, front_desk])
    await db_session.commit()
    case = await _case(db_session)

    with pytest.raises(NotADoctorError):
        await appointment_service.book_appointment(
            db_session, front_desk.id, case.id, _slot(), admin
        )


async def test_book_appointment_missing_case_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()

    with pytest.raises(CaseNotFoundError):
        await appointment_service.book_appointment(db_session, doctor.id, uuid4(), _slot(), admin)


async def test_book_appointment_duplicate_slot_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case1 = await _case(db_session)
    case2 = await _case(db_session)
    slot = _slot()

    await appointment_service.book_appointment(db_session, doctor.id, case1.id, slot, admin)
    with pytest.raises(SlotTakenError):
        await appointment_service.book_appointment(db_session, doctor.id, case2.id, slot, admin)


async def test_list_appointments_scoped_to_doctor(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor_a = _user(UserRole.DOCTOR)
    doctor_b = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor_a, doctor_b])
    await db_session.commit()
    case = await _case(db_session)

    await appointment_service.book_appointment(db_session, doctor_a.id, case.id, _slot(1), admin)
    await appointment_service.book_appointment(db_session, doctor_b.id, case.id, _slot(2), admin)

    items, total = await appointment_service.list_appointments(db_session, doctor_id=doctor_a.id)
    assert total == 1
    assert items[0].doctor_id == doctor_a.id

    items, total = await appointment_service.list_appointments(db_session)
    assert total == 2


async def test_reschedule_appointment_updates_time_slot(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case = await _case(db_session)
    appointment = await appointment_service.book_appointment(
        db_session, doctor.id, case.id, _slot(1), admin
    )
    new_slot = _slot(2)

    updated = await appointment_service.reschedule_appointment(
        db_session, appointment.id, new_slot, admin, scoped_doctor_id=None
    )

    assert updated is not None
    # SQLite (this suite's default DB) doesn't persist tzinfo on DateTime
    # columns, so the round-tripped value comes back naive even though the
    # wall-clock value is unchanged; normalize both sides before comparing.
    assert updated.time_slot.replace(tzinfo=None) == new_slot.replace(tzinfo=None)


async def test_reschedule_appointment_out_of_scope_returns_none(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor_a = _user(UserRole.DOCTOR)
    doctor_b = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor_a, doctor_b])
    await db_session.commit()
    case = await _case(db_session)
    appointment = await appointment_service.book_appointment(
        db_session, doctor_a.id, case.id, _slot(1), admin
    )

    result = await appointment_service.reschedule_appointment(
        db_session, appointment.id, _slot(2), doctor_b, scoped_doctor_id=doctor_b.id
    )
    assert result is None


async def test_reschedule_cancelled_appointment_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case = await _case(db_session)
    appointment = await appointment_service.book_appointment(
        db_session, doctor.id, case.id, _slot(1), admin
    )
    await appointment_service.cancel_appointment(
        db_session, appointment.id, admin, scoped_doctor_id=None
    )

    with pytest.raises(AppointmentStateError):
        await appointment_service.reschedule_appointment(
            db_session, appointment.id, _slot(2), admin, scoped_doctor_id=None
        )


async def test_reschedule_into_taken_slot_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case = await _case(db_session)
    slot_a = _slot(1)
    slot_b = _slot(2)
    await appointment_service.book_appointment(db_session, doctor.id, case.id, slot_a, admin)
    appointment_b = await appointment_service.book_appointment(
        db_session, doctor.id, case.id, slot_b, admin
    )

    with pytest.raises(SlotTakenError):
        await appointment_service.reschedule_appointment(
            db_session, appointment_b.id, slot_a, admin, scoped_doctor_id=None
        )


async def test_cancel_appointment_soft_cancels_and_audits(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case = await _case(db_session)
    appointment = await appointment_service.book_appointment(
        db_session, doctor.id, case.id, _slot(1), admin
    )

    cancelled = await appointment_service.cancel_appointment(
        db_session, appointment.id, admin, scoped_doctor_id=None
    )

    assert cancelled is not None
    assert cancelled.status == AppointmentStatus.CANCELLED
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "appointment.cancelled", AuditEvent.case_id == case.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


async def test_cancel_appointment_out_of_scope_returns_none(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor_a = _user(UserRole.DOCTOR)
    doctor_b = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor_a, doctor_b])
    await db_session.commit()
    case = await _case(db_session)
    appointment = await appointment_service.book_appointment(
        db_session, doctor_a.id, case.id, _slot(1), admin
    )

    result = await appointment_service.cancel_appointment(
        db_session, appointment.id, doctor_b, scoped_doctor_id=doctor_b.id
    )
    assert result is None


async def test_cancel_appointment_twice_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    case = await _case(db_session)
    appointment = await appointment_service.book_appointment(
        db_session, doctor.id, case.id, _slot(1), admin
    )
    await appointment_service.cancel_appointment(
        db_session, appointment.id, admin, scoped_doctor_id=None
    )

    with pytest.raises(AppointmentStateError):
        await appointment_service.cancel_appointment(
            db_session, appointment.id, admin, scoped_doctor_id=None
        )
