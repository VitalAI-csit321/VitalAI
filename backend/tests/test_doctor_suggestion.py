from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import DoctorPatientAssignment
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.services.doctor_suggestion import suggest_doctor_for_patient


def _doctor(label: str) -> User:
    return User(
        email=f"doc-{label}-{uuid4().hex[:6]}@example.com",
        hashed_password="h",
        full_name=f"Doctor {label}",
        role=UserRole.DOCTOR,
    )


async def test_suggest_doctor_returns_none_when_no_doctors_exist(
    db_session: AsyncSession, patient: Patient
):
    result = await suggest_doctor_for_patient(db_session, patient.id)
    assert result is None


async def test_suggest_doctor_picks_least_loaded(db_session: AsyncSession, patient: Patient):
    busy = _doctor("busy")
    idle = _doctor("idle")
    db_session.add_all([busy, idle])
    await db_session.commit()
    await db_session.refresh(busy)
    await db_session.refresh(idle)

    other_patient = Patient(
        mrn="MRN-SUGGEST01",
        name="Other Patient",
        dob=patient.dob,
        gender=patient.gender,
        status=patient.status,
    )
    db_session.add(other_patient)
    await db_session.commit()
    await db_session.refresh(other_patient)
    db_session.add(
        DoctorPatientAssignment(doctor_id=busy.id, patient_id=other_patient.id, assigned_by=busy.id)
    )
    await db_session.commit()

    result = await suggest_doctor_for_patient(db_session, patient.id)

    assert result == idle.id


async def test_suggest_doctor_is_deterministic_on_ties(db_session: AsyncSession, patient: Patient):
    a = _doctor("a")
    b = _doctor("b")
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)

    first = await suggest_doctor_for_patient(db_session, patient.id)
    second = await suggest_doctor_for_patient(db_session, patient.id)

    assert first == second
    assert first in {a.id, b.id}