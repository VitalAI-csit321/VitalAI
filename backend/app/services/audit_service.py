from uuid import UUID

from sqlalchemy import select
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
