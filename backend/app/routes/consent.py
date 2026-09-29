from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import CAPTURE_CONSENT, VIEW_RECORDS_GENERAL
from app.auth.scoping import is_assigned
from app.database import get_db
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.schemas.consent import (
    ConsentCaptureIn,
    ConsentCreate,
    ConsentOut,
    ConsentQueueResponse,
    ConsentQueueRow,
    ConsentVerifyIn,
)
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


@router.get("", response_model=list[ConsentOut])
async def list_consents_for_patient_endpoint(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    if actor.role == UserRole.DOCTOR and not await is_assigned(db, actor.id, patient_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    return await consent_service.list_consents_for_patient(db, patient_id)


@router.get("/queue", response_model=ConsentQueueResponse)
async def consent_queue_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(CAPTURE_CONSENT)),
):
    """The staff consent queue: real records, not the recent cases.

    Gated on CAPTURE_CONSENT, which front desk, operators and admins hold and
    clinicians do not, because this is the whole-clinic administrative view of
    who has been asked for consent. Scoping it per assignment instead would
    hand a clinician a partial list that reads as complete. Declared through
    the permission rather than a role check in the body, so the RBAC registry
    stays the single description of who may call this.
    """
    rows, total = await consent_service.list_consent_queue(db, limit=limit, offset=offset)
    return ConsentQueueResponse(
        items=[
            ConsentQueueRow(
                id=record.id,
                case_id=record.case_id,
                patient_name=patient_name,
                consent_type=record.consent_type,
                status=record.status,
                created_at=record.created_at,
                captured_at=record.captured_at,
            )
            for record, patient_name in rows
        ],
        total=total,
    )


@router.get("/by-case/{case_id}", response_model=ConsentOut)
async def get_consent_by_case_endpoint(
    case_id: UUID,
    # A case can hold several records; the consent queue names the one it listed.
    consent_id: UUID | None = None,
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

    if consent_id is None:
        record = await consent_service.get_consent_for_case(db, case_id)
    else:
        record = await db.get(ConsentRecord, consent_id)
        if record is not None and record.case_id != case_id:
            record = None
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )
    return record


@router.post("/{consent_id}/capture", response_model=ConsentOut)
async def capture_consent_endpoint(
    consent_id: UUID,
    payload: ConsentCaptureIn | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(CAPTURE_CONSENT)),
):
    form_snapshot = (
        payload.form_snapshot.model_dump() if payload and payload.form_snapshot else None
    )
    try:
        record = await consent_service.capture_consent(db, consent_id, actor, form_snapshot)
    except ConsentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )
    return record


@router.post("/{consent_id}/verify", response_model=ConsentOut)
async def verify_consent_endpoint(
    consent_id: UUID,
    payload: ConsentVerifyIn | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(CAPTURE_CONSENT)),
):
    """Staff checked ID for a patient who registered online, and finished
    anything the patient left for the clinic."""
    try:
        record = await consent_service.verify_online_consent(
            db,
            consent_id,
            actor,
            checks=payload.checks if payload else None,
            signature=payload.signature if payload else None,
        )
    except ConsentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consent record not found"
        )
    return record


@router.post("/{consent_id}/resolve-review", response_model=ConsentOut)
async def resolve_review_endpoint(
    consent_id: UUID,
    payload: ConsentCaptureIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(CAPTURE_CONSENT)),
):
    if payload.form_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="form_snapshot is required"
        )
    try:
        record = await consent_service.update_consent_checklist(
            db, consent_id, actor, payload.form_snapshot.model_dump()
        )
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
