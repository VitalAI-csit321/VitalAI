from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase, IntakeStatus
from app.models.patient import Patient
from app.models.user import User
from app.schemas.case import IntakeCreate
from app.services.audit_service import record_event


class PatientNotFoundError(Exception):
    """Raised when IntakeCreate.patient_id does not reference an existing patient."""


async def create_intake(db: AsyncSession, payload: IntakeCreate, actor: User) -> IntakeCase:
    patient = await db.get(Patient, payload.patient_id)
    if patient is None:
        raise PatientNotFoundError(f"Patient {payload.patient_id} not found")

    case = IntakeCase(
        patient_id=payload.patient_id,
        contact_reason=payload.contact_reason,
        contact_channel=payload.contact_channel,
        notes=payload.notes,
        status=IntakeStatus.RECEIVED,
    )
    db.add(case)
    await db.flush()  # populates case.id

    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="intake.created",
        details={"channel": payload.contact_channel},
    )
    await db.commit()
    await db.refresh(case)
    return case


async def get_case(db: AsyncSession, case_id: UUID) -> IntakeCase | None:
    return await db.get(IntakeCase, case_id)


async def update_case_status(
    db: AsyncSession, case_id: UUID, status: IntakeStatus, actor: User
) -> IntakeCase | None:
    case = await db.get(IntakeCase, case_id)
    if case is None:
        return None

    old_status = case.status
    case.status = status

    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="intake.status_changed",
        details={"from": old_status.value, "to": status.value},
    )
    await db.commit()
    await db.refresh(case)
    return case
