from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import DoctorPatientAssignment
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.services.audit_service import record_event


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
