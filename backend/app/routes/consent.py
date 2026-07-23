from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import CAPTURE_CONSENT, VIEW_RECORDS_GENERAL
from app.auth.scoping import is_assigned
from app.database import get_db
from app.models.case import IntakeCase
from app.models.user import User, UserRole
from app.schemas.consent import ConsentCreate, ConsentOut
from app.services import consent_service
from app.services.consent_service import ConsentStateError

router = APIRouter(prefix="/consent", tags=["consent"])


@router.post("", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def create_consent_endpoint(
    payload: ConsentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(CAPTURE_CONSENT)),
):
    return await consent_service.create_consent_record(
        db, payload.case_id, actor, payload.consent_type, payload.notes
    )


@router.get("/by-case/{case_id}", response_model=ConsentOut)
async def get_consent_by_case_endpoint(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    case = await db.get(IntakeCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )

    if actor.role == UserRole.DOCTOR:
        # Fail closed: an unlinked legacy case (patient_id is None) can't be
        # checked against the doctor's assignment set, so it's treated the
        # same as "not found" rather than distinguishing exists-but-forbidden.
        if case.patient_id is None or not await is_assigned(db, actor.id, case.patient_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
            )

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
    actor: User = Depends(require_permission(CAPTURE_CONSENT)),
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
    actor: User = Depends(require_permission(CAPTURE_CONSENT)),
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
