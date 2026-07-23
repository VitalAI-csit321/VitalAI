from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.routing import RoutingAction
from app.models.user import User
from app.schemas.pagination import Page, PageParams
from app.schemas.routing import RoutingCreate, RoutingOut
from app.services import routing_service

router = APIRouter(prefix="/routing", tags=["routing"])


@router.post("", response_model=RoutingOut, status_code=status.HTTP_201_CREATED)
async def route_endpoint(
    payload: RoutingCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    decision = await routing_service.route_from_triage_id(db, payload.triage_id, actor)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"TriageResult {payload.triage_id} not found",
        )
    return decision


@router.get("", response_model=Page[RoutingOut])
async def list_routing_endpoint(
    page: PageParams = Depends(),
    target_queue: list[str] | None = Query(default=None),
    action: list[RoutingAction] | None = Query(default=None),
    escalated: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Routing decisions, filterable by queue — backs the Escalation Routing Board."""
    items, total = await routing_service.list_decisions(
        db,
        limit=page.limit,
        offset=page.offset,
        target_queue=target_queue,
        action=action,
        escalated=escalated,
    )
    return Page[RoutingOut](
        items=[RoutingOut.model_validate(decision) for decision in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/summary")
async def routing_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, dict[str, int]]:
    """Decision counts per queue — the board's column headers."""
    return {"queue_counts": await routing_service.queue_counts(db)}


@router.get("/by-case/{case_id}", response_model=RoutingOut)
async def get_routing_endpoint(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    decision = await routing_service.get_decision_for_case(db, case_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Routing decision not found"
        )
    return decision
