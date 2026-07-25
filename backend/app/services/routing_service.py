"""Routing service — takes a triage result, applies routing rules,
persists a RoutingDecision. Distinct from triage classification.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.routing import RoutingDecision
from app.models.triage import TriageResult
from app.models.user import User
from app.services.audit_service import record_event
from app.services.routing_rules import decide


async def route_from_triage_id(
    db: AsyncSession, triage_id: UUID, actor: User
) -> RoutingDecision | None:
    triage = await db.get(TriageResult, triage_id)
    if triage is None:
        return None

    action, target_queue, escalated = decide(triage.category)

    decision = RoutingDecision(
        case_id=triage.case_id,
        triage_id=triage.id,
        action=action,
        target_queue=target_queue,
        escalated=escalated,
    )
    db.add(decision)
    triage.routed = True
    await db.flush()

    await record_event(
        db,
        case_id=triage.case_id,
        actor=actor,
        action="routing.decided",
        details={
            "routing_id": str(decision.id),
            "action": action.value,
            "target_queue": target_queue,
            "escalated": escalated,
        },
    )
    await db.commit()
    await db.refresh(decision)
    return decision


async def get_decision_for_case(db: AsyncSession, case_id: UUID) -> RoutingDecision | None:
    result = await db.execute(
        select(RoutingDecision)
        .where(RoutingDecision.case_id == case_id)
        .order_by(RoutingDecision.created_at.desc())
    )
    return result.scalars().first()
