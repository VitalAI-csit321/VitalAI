from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_context import get_ip_address, get_session_id
from app.models.audit import AuditEvent
from app.models.user import User

_HIGH_RISK_ACTIONS = {"governance.access_denied", "governance.input_blocked"}
_MEDIUM_RISK_KEYWORDS = ("escalat", "triage", "routing")
_BLOCKED_ACTIONS = {"governance.access_denied", "governance.input_blocked"}


def risk_level_from_score(score: int | None) -> str:
    if score is None:
        return "Low"
    if score >= 70:
        return "High"
    if score >= 30:
        return "Medium"
    return "Low"


def _compute_risk_score(action: str) -> int:
    if action in _HIGH_RISK_ACTIONS:
        return 90
    if any(keyword in action for keyword in _MEDIUM_RISK_KEYWORDS):
        return 50
    return 10


def _compute_outcome(action: str) -> str:
    return "BLOCKED" if action in _BLOCKED_ACTIONS else "SUCCESS"


async def record_event(
    db: AsyncSession,
    *,
    action: str,
    case_id: UUID | None = None,
    actor: User | None = None,
    actor_label: str | None = None,
    details: dict | None = None,
) -> AuditEvent:
    """Append a new audit event and flush it to the session.

    This function flushes but does NOT commit. The caller is responsible for
    committing so that the audit event and the associated business change
    (e.g. consent captured, triage created) are persisted atomically in the
    same transaction. Never call db.commit() inside this function.

    actor_label overrides the label derived from `actor` - used by call
    sites (e.g. app.rag.retrieval) that have a label string but no real
    User object to attach as actor_id/actor_role.
    """
    event = AuditEvent(
        case_id=case_id,
        actor_id=actor.id if actor else None,
        actor_label=actor_label
        if actor_label is not None
        else (actor.email if actor else "system"),
        actor_role=actor.role.value if actor else None,
        action=action,
        details=details or {},
        risk_score=_compute_risk_score(action),
        outcome=_compute_outcome(action),
        ip_address=get_ip_address(),
        session_id=get_session_id(),
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
    actor_id: UUID | None = None,
    action: str | None = None,
    risk_level: str | None = None,
    outcome: str | None = None,
    case_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    filters = []
    if actor_id is not None:
        filters.append(AuditEvent.actor_id == actor_id)
    if action is not None:
        filters.append(AuditEvent.action == action)
    if outcome is not None:
        filters.append(AuditEvent.outcome == outcome)
    if case_id is not None:
        filters.append(AuditEvent.case_id == case_id)
    if from_time is not None:
        filters.append(AuditEvent.timestamp >= from_time)
    if to_time is not None:
        filters.append(AuditEvent.timestamp <= to_time)
    if risk_level == "High":
        filters.append(AuditEvent.risk_score >= 70)
    elif risk_level == "Medium":
        filters.append(and_(AuditEvent.risk_score >= 30, AuditEvent.risk_score < 70))
    elif risk_level == "Low":
        filters.append(or_(AuditEvent.risk_score < 30, AuditEvent.risk_score.is_(None)))

    total = (
        await db.execute(select(func.count()).select_from(AuditEvent).where(*filters))
    ).scalar_one()

    result = await db.execute(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(result.scalars().all())
    return items, total


async def get_event_by_id(db: AsyncSession, event_id: UUID) -> AuditEvent | None:
    return await db.get(AuditEvent, event_id)


async def verify_chain(db: AsyncSession) -> dict:
    result = await db.execute(
        text("SELECT valid, checked_count, first_break_event_id FROM verify_audit_chain()")
    )
    row = result.one()
    return {
        "valid": row.valid,
        "checked_count": row.checked_count,
        "first_break_event_id": str(row.first_break_event_id) if row.first_break_event_id else None,
    }
