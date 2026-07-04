from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.case import IntakeCaseOut, IntakeCreate, IntakeStatusUpdate
from app.services import intake_service

router = APIRouter(prefix="/intake", tags=["intake"])


@router.post("", response_model=IntakeCaseOut, status_code=status.HTTP_201_CREATED)
async def create_intake_endpoint(
    payload: IntakeCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return await intake_service.create_intake(db, payload, actor)


@router.get("/{case_id}", response_model=IntakeCaseOut)
async def get_intake_endpoint(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    case = await intake_service.get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


@router.patch("/{case_id}/status", response_model=IntakeCaseOut)
async def update_intake_status_endpoint(
    case_id: UUID,
    payload: IntakeStatusUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_roles(UserRole.OPS_MANAGER, UserRole.ADMIN)),
):
    case = await intake_service.update_case_status(db, case_id, payload.status, actor)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case
