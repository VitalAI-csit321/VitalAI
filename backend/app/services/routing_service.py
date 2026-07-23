"""Routing service — takes a triage result, applies routing rules,
persists a RoutingDecision. Distinct from triage classification.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.routing import RoutingAction, RoutingDecision
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


async def list_decisions(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    target_queue: list[str] | None = None,
    action: list[RoutingAction] | None = None,
    escalated: bool | None = None,
) -> tuple[list[RoutingDecision], int]:
    """Return (page_of_decisions, total). Backs the Escalation Routing Board.

    Escalated items first, then oldest — an escalation that has been waiting is
    the most urgent thing on the board, so neither pure-newest nor pure-oldest
    ordering is right on its own.
    """
    filters = []
    if target_queue:
        filters.append(RoutingDecision.target_queue.in_(target_queue))
    if action:
        filters.append(RoutingDecision.action.in_(action))
    if escalated is not None:
        filters.append(RoutingDecision.escalated == escalated)

    count_stmt = select(func.count()).select_from(RoutingDecision)
    page_stmt = select(RoutingDecision)
    if filters:
        count_stmt = count_stmt.where(*filters)
        page_stmt = page_stmt.where(*filters)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(
        page_stmt.order_by(RoutingDecision.escalated.desc(), RoutingDecision.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def queue_counts(db: AsyncSession) -> dict[str, int]:
    """Decision count per target_queue — the routing board's column headers."""
    result = await db.execute(
        select(RoutingDecision.target_queue, func.count(RoutingDecision.id)).group_by(
            RoutingDecision.target_queue
        )
    )
    return {queue: count for queue, count in result.all()}
