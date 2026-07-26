from uuid import UUID

from sqlalchemy import func, or_, select
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
        patient_name=patient.name,
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


async def list_cases(
    db: AsyncSession,
    search: str | None = None,
    status: list[IntakeStatus] | None = None,
    channel: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[IntakeCase], int]:
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(
            or_(IntakeCase.patient_name.ilike(term), IntakeCase.contact_reason.ilike(term))
        )
    if status:
        filters.append(IntakeCase.status.in_(status))
    if channel:
        filters.append(IntakeCase.contact_channel == channel)

    items_query = select(IntakeCase)
    count_query = select(func.count()).select_from(IntakeCase)
    for condition in filters:
        items_query = items_query.where(condition)
        count_query = count_query.where(condition)

    items_result = await db.execute(
        items_query.order_by(IntakeCase.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(items_result.scalars().all())
    total = (await db.execute(count_query)).scalar_one()

    return items, total


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
