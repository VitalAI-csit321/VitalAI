from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.user import User


async def record_event(
    db: AsyncSession,
    *,
    action: str,
    case_id: UUID | None = None,
    actor: User | None = None,
    details: dict | None = None,
) -> AuditEvent:
    """Append a new audit event and flush it to the session.

    This function flushes but does NOT commit. The caller is responsible for
    committing so that the audit event and the associated business change
    (e.g. consent captured, triage created) are persisted atomically in the
    same transaction. Never call db.commit() inside this function.
    """
    event = AuditEvent(
        case_id=case_id,
        actor_id=actor.id if actor else None,
        actor_label=actor.email if actor else "system",
        action=action,
        details=details or {},
    )
    db.add(event)
    await db.flush()  # commit happens at the route layer
    return event


async def get_events_for_case(db: AsyncSession, case_id: UUID) -> list[AuditEvent]:
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.timestamp)
    )
    return list(result.scalars().all())


async def list_events(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    action: list[str] | None = None,
    actor_id: UUID | None = None,
    case_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[AuditEvent], int]:
    """Return (page_of_events, total_matching_count), newest first.

    Backs the global Audit Logs page. The table is append-only (enforced by a
    DB trigger from migration 0001), so there is no update/delete counterpart
    here by design.
    """
    filters = []
    if action:
        filters.append(AuditEvent.action.in_(action))
    if actor_id is not None:
        filters.append(AuditEvent.actor_id == actor_id)
    if case_id is not None:
        filters.append(AuditEvent.case_id == case_id)
    if since is not None:
        filters.append(AuditEvent.timestamp >= since)
    if until is not None:
        filters.append(AuditEvent.timestamp <= until)

    count_stmt = select(func.count()).select_from(AuditEvent)
    page_stmt = select(AuditEvent)
    if filters:
        count_stmt = count_stmt.where(*filters)
        page_stmt = page_stmt.where(*filters)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(
        page_stmt.order_by(AuditEvent.timestamp.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def list_actions(db: AsyncSession) -> list[str]:
    """Distinct action values present — populates the audit filter dropdown."""
    result = await db.execute(select(AuditEvent.action).distinct().order_by(AuditEvent.action))
    return list(result.scalars().all())
