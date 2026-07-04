from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.consent import ConsentCreate, ConsentOut
from app.services import consent_service
from app.services.consent_service import ConsentStateError

router = APIRouter(prefix="/consent", tags=["consent"])


@router.post("", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def create_consent_endpoint(
    payload: ConsentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return await consent_service.create_consent_record(
        db, payload.case_id, actor, payload.consent_type, payload.notes
    )


@router.get("/by-case/{case_id}", response_model=ConsentOut)
async def get_consent_by_case_endpoint(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = await consent_service.get_consent_for_case(db, case_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )
    return record


@router.post("/{consent_id}/capture", response_model=ConsentOut)
async def capture_consent_endpoint(
    consent_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    try:
        record = await consent_service.capture_consent(db, consent_id, actor)
    except ConsentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )
    return record


@router.post("/{consent_id}/withdraw", response_model=ConsentOut)
async def withdraw_consent_endpoint(
    consent_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    try:
        record = await consent_service.withdraw_consent(db, consent_id, actor)
    except ConsentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )
    return record
