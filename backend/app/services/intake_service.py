from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase, IntakeStatus
from app.models.user import User
from app.schemas.case import IntakeCreate
from app.services.audit_service import record_event


async def create_intake(db: AsyncSession, payload: IntakeCreate, actor: User) -> IntakeCase:
    case = IntakeCase(
        patient_name=payload.patient_name,
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
    *,
    limit: int,
    offset: int,
    status: list[IntakeStatus] | None = None,
    channel: str | None = None,
    search: str | None = None,
) -> tuple[list[IntakeCase], int]:
    """Return (page_of_cases, total_matching_count).

    Filters are ANDed; `status` is an OR within itself so the dashboard can ask
    for e.g. all three triage_* states at once. Newest first — the front desk
    cares about what just came in.
    """
    filters = []
    if status:
        filters.append(IntakeCase.status.in_(status))
    if channel:
        filters.append(IntakeCase.contact_channel == channel)
    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(
                IntakeCase.patient_name.ilike(pattern),
                IntakeCase.contact_reason.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(IntakeCase)
    page_stmt = select(IntakeCase)
    if filters:
        count_stmt = count_stmt.where(*filters)
        page_stmt = page_stmt.where(*filters)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(
        page_stmt.order_by(IntakeCase.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def status_counts(db: AsyncSession) -> dict[str, int]:
    """Case count per status, for the dashboard tiles.

    Statuses with zero cases are included as 0 so the dashboard renders a
    stable set of tiles instead of shifting layout as data changes.
    """
    result = await db.execute(
        select(IntakeCase.status, func.count(IntakeCase.id)).group_by(IntakeCase.status)
    )
    counts = {status.value: 0 for status in IntakeStatus}
    for status, count in result.all():
        counts[status.value] = count
    return counts


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
