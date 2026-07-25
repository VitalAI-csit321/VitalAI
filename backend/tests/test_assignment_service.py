from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.patient import Gender, Patient, PatientStatus
from app.models.user import User, UserRole
from app.services import assignment_service
from app.services.assignment_service import (
    AssignmentExistsError,
    DoctorNotFoundError,
    NotADoctorError,
    PatientNotFoundError,
)


def _user(role: UserRole) -> User:
    return User(
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        hashed_password="h",
        full_name="X",
        role=role,
    )


async def _patient(db_session: AsyncSession) -> Patient:
    p = Patient(
        mrn=f"MRN-{uuid4().hex[:8].upper()}",
        name="Assignment Test Patient",
        dob=date(1990, 1, 1),
        gender=Gender.MALE,
        status=PatientStatus.ACTIVE,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def test_assign_patient_creates_and_audits(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    patient = await _patient(db_session)

    assignment = await assignment_service.assign_patient(db_session, doctor.id, patient.id, admin)

    assert assignment.doctor_id == doctor.id
    assert assignment.patient_id == patient.id
    assert assignment.assigned_by == admin.id

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "assignment.created", AuditEvent.actor_id == admin.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].details["doctor_id"] == str(doctor.id)


async def test_assign_patient_duplicate_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    patient = await _patient(db_session)

    await assignment_service.assign_patient(db_session, doctor.id, patient.id, admin)

    with pytest.raises(AssignmentExistsError):
        await assignment_service.assign_patient(db_session, doctor.id, patient.id, admin)


async def test_assign_patient_missing_doctor_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    patient = await _patient(db_session)

    with pytest.raises(DoctorNotFoundError):
        await assignment_service.assign_patient(db_session, uuid4(), patient.id, admin)


async def test_assign_patient_non_doctor_role_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    front_desk = _user(UserRole.FRONT_DESK)
    db_session.add_all([admin, front_desk])
    await db_session.commit()
    patient = await _patient(db_session)

    with pytest.raises(NotADoctorError):
        await assignment_service.assign_patient(db_session, front_desk.id, patient.id, admin)


async def test_assign_patient_missing_patient_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()

    with pytest.raises(PatientNotFoundError):
        await assignment_service.assign_patient(db_session, doctor.id, uuid4(), admin)


async def test_unassign_patient_removes_and_audits(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    patient = await _patient(db_session)
    await assignment_service.assign_patient(db_session, doctor.id, patient.id, admin)

    deleted = await assignment_service.unassign_patient(db_session, doctor.id, patient.id, admin)
    assert deleted is True

    remaining = await assignment_service.list_assignments(db_session, doctor.id)
    assert remaining == []


async def test_unassign_patient_missing_returns_false(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()

    deleted = await assignment_service.unassign_patient(db_session, doctor.id, uuid4(), admin)
    assert deleted is False


async def test_list_assignments_scoped_to_doctor(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    doctor_a = _user(UserRole.DOCTOR)
    doctor_b = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor_a, doctor_b])
    await db_session.commit()
    patient = await _patient(db_session)

    await assignment_service.assign_patient(db_session, doctor_a.id, patient.id, admin)

    assert len(await assignment_service.list_assignments(db_session, doctor_a.id)) == 1
    assert len(await assignment_service.list_assignments(db_session, doctor_b.id)) == 0
