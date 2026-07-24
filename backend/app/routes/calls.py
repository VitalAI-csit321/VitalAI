from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.permissions import VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.call import CallCreate, CallOut
from app.services import call_service

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_call_endpoint(
    payload: CallCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    try:
        return await call_service.create_call(db, payload, actor)
    except call_service.CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[CallOut])
async def list_calls_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    return await call_service.list_calls(db)


@router.get("/{call_id}", response_model=CallOut)
async def get_call_endpoint(
    call_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    call = await call_service.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call
