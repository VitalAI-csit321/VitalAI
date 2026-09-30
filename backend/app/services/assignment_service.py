from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import DoctorPatientAssignment
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.services.audit_service import record_event
from app.services.doctor_suggestion import suggest_doctor_for_patient


class AssignmentExistsError(Exception):
    """Raised when a (doctor_id, patient_id) pair is already assigned."""


class DoctorNotFoundError(Exception):
    """Raised when doctor_id doesn't reference an existing user."""


class NotADoctorError(Exception):
    """Raised when doctor_id references a user whose role isn't DOCTOR."""


class PatientNotFoundError(Exception):
    """Raised when patient_id doesn't reference an existing patient."""


async def assign_patient(
    db: AsyncSession, doctor_id: UUID, patient_id: UUID, actor: User
) -> DoctorPatientAssignment:
    # Validated up front so a bogus doctor_id/patient_id can't slip through as
    # a "successful" assignment, and so the later IntegrityError catch can
    # only mean one thing: the composite PK already exists.
    doctor = await db.get(User, doctor_id)
    if doctor is None:
        raise DoctorNotFoundError(f"No user with id {doctor_id}")
    if doctor.role != UserRole.DOCTOR:
        raise NotADoctorError(f"User {doctor_id} has role '{doctor.role.value}', not 'doctor'")
    if await db.get(Patient, patient_id) is None:
        raise PatientNotFoundError(f"No patient with id {patient_id}")

    assignment = DoctorPatientAssignment(
        doctor_id=doctor_id, patient_id=patient_id, assigned_by=actor.id
    )
    db.add(assignment)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AssignmentExistsError(
            f"Patient {patient_id} is already assigned to doctor {doctor_id}"
        ) from exc

    await record_event(
        db,
        actor=actor,
        action="assignment.created",
        details={"doctor_id": str(doctor_id), "patient_id": str(patient_id)},
    )
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def unassign_patient(
    db: AsyncSession, doctor_id: UUID, patient_id: UUID, actor: User
) -> bool:
    assignment = await db.get(DoctorPatientAssignment, (doctor_id, patient_id))
    if assignment is None:
        return False

    await db.delete(assignment)
    await record_event(
        db,
        actor=actor,
        action="assignment.deleted",
        details={"doctor_id": str(doctor_id), "patient_id": str(patient_id)},
    )
    await db.commit()
    return True


async def list_assignments(db: AsyncSession, doctor_id: UUID) -> list[DoctorPatientAssignment]:
    result = await db.execute(
        select(DoctorPatientAssignment).where(DoctorPatientAssignment.doctor_id == doctor_id)
    )
    return list(result.scalars().all())


async def _active_doctor(db: AsyncSession, doctor_id: UUID | None) -> User | None:
    doctor = await db.get(User, doctor_id) if doctor_id is not None else None
    if doctor is None or doctor.role != UserRole.DOCTOR or not doctor.is_active:
        return None
    return doctor


async def ensure_doctor(db: AsyncSession, patient: Patient, actor: User) -> UUID | None:
    """M4 spec E6: a registered patient with no active doctor gets one now,
    their preference while that doctor is active, else the least-loaded
    active doctor. Returns the doctor assigned, None when nothing changed
    (already has one, provisional or purged, or no active doctor exists).
    Flushes, never commits: it runs inside patient creation and promotion."""
    # Imported here: booking_service -> appointment_service -> patient_service,
    # which calls this module.
    from app.services.booking_service import doctor_for_patient

    if patient.is_provisional or patient.purged_at is not None:
        return None
    if await doctor_for_patient(db, patient.id) is not None:
        return None
    preferred = await _active_doctor(db, patient.preferred_doctor_id)
    doctor_id = preferred.id if preferred else await suggest_doctor_for_patient(db, patient.id)
    if doctor_id is None:
        return None
    # An inactive doctor's old assignment may still be there; this pair is new
    # only if they are a different doctor.
    if await db.get(DoctorPatientAssignment, (doctor_id, patient.id)) is None:
        db.add(
            DoctorPatientAssignment(
                doctor_id=doctor_id, patient_id=patient.id, assigned_by=actor.id
            )
        )
        await db.flush()
    await record_event(
        db,
        actor=actor,
        action="patient.doctor_assigned",
        details={
            "patient_id": str(patient.id),
            "doctor_id": str(doctor_id),
            "reason": "preference" if preferred else "least_loaded",
        },
    )
    return doctor_id


async def change_doctor(db: AsyncSession, patient: Patient, doctor_id: UUID, actor: User) -> None:
    """Staff change who the patient's doctor is (E6: changeable). The new
    doctor is assigned and the previous one (booking_service.doctor_for_patient,
    the longest-standing) loses the assignment, so the new one is the answer
    from now on. Other assignments (e.g. a case doctor) stay. Commits."""
    from app.services.booking_service import doctor_for_patient

    doctor = await _active_doctor(db, doctor_id)
    if doctor is None:
        raise NotADoctorError(f"User {doctor_id} is not an active doctor")
    previous = await doctor_for_patient(db, patient.id)
    if previous is not None and previous[0] != doctor.id:
        old = await db.get(DoctorPatientAssignment, (previous[0], patient.id))
        if old is not None:
            await db.delete(old)
    if await db.get(DoctorPatientAssignment, (doctor.id, patient.id)) is None:
        db.add(
            DoctorPatientAssignment(
                doctor_id=doctor.id, patient_id=patient.id, assigned_by=actor.id
            )
        )
    await db.flush()
    await record_event(
        db,
        actor=actor,
        action="patient.doctor_assigned",
        details={
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "previous_doctor_id": str(previous[0]) if previous else None,
            "reason": "staff",
        },
    )
    await db.commit()
