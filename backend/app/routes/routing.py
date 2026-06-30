from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
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
