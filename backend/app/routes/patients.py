from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import (
    ASSIGN_PATIENTS,
    REGISTER_PATIENT,
    VIEW_RECORDS_GENERAL,
    effective_permissions,
)
from app.database import get_db
from app.models.patient import Patient, PatientStatus
from app.models.user import User, UserRole
from app.schemas.patient import (
    PatientCounts,
    PatientCreate,
    PatientDoctorChange,
    PatientListResponse,
    PatientOut,
    PatientUpdate,
)
from app.services import assignment_service, booking_service, patient_service

router = APIRouter(prefix="/patients", tags=["patients"])


async def _out(db: AsyncSession, patient: Patient) -> PatientOut:
    """One patient, with who their doctor is (E6)."""
    doctor = await booking_service.doctor_for_patient(db, patient.id)
    return PatientOut.model_validate(patient).model_copy(
        update={
            "doctor_id": doctor[0] if doctor else None,
            "doctor_name": doctor[1] if doctor else None,
        }
    )


def _bad_preference(exc: patient_service.PreferredDoctorError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient_endpoint(
    payload: PatientCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(REGISTER_PATIENT)),
):
    try:
        patient = await patient_service.create_patient(db, payload, actor)
    except patient_service.PreferredDoctorError as exc:
        raise _bad_preference(exc) from exc
    return await _out(db, patient)


@router.get("", response_model=PatientListResponse)
async def list_patients_endpoint(
    search: str | None = None,
    status: PatientStatus | None = None,
    sort: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    doctor_id = actor.id if actor.role == UserRole.DOCTOR else None
    items, total, counts = await patient_service.list_patients(
        db,
        search=search,
        status=status,
        sort=sort,
        limit=limit,
        offset=offset,
        doctor_id=doctor_id,
        # Only staff who can register patients can see the provisional ones,
        # so they can find and promote them. Doctors never do.
        include_provisional=REGISTER_PATIENT in effective_permissions(actor),
    )
    return PatientListResponse(
        items=[PatientOut.model_validate(p) for p in items],
        total=total,
        counts=PatientCounts(**counts),
    )


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient_endpoint(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    doctor_id = actor.id if actor.role == UserRole.DOCTOR else None
    patient = await patient_service.get_patient_by_id(
        db,
        patient_id,
        doctor_id,
        include_provisional=REGISTER_PATIENT in effective_permissions(actor),
    )
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return await _out(db, patient)


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient_endpoint(
    patient_id: UUID,
    payload: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(REGISTER_PATIENT)),
):
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    try:
        patient = await patient_service.update_patient(db, patient, payload, actor)
    except patient_service.PreferredDoctorError as exc:
        raise _bad_preference(exc) from exc
    return await _out(db, patient)


@router.post("/{patient_id}/promote", response_model=PatientOut)
async def promote_patient_endpoint(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(REGISTER_PATIENT)),
):
    """Provisional -> registered. Human-only, and only once explicit consent
    has been captured through the ordinary consent flow."""
    try:
        patient = await patient_service.promote_patient(db, patient_id, actor)
    except patient_service.PromotionRefusedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return await _out(db, patient)


@router.put("/{patient_id}/doctor", response_model=PatientOut)
async def change_patient_doctor_endpoint(
    patient_id: UUID,
    payload: PatientDoctorChange,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(ASSIGN_PATIENTS)),
):
    """Who the patient's doctor is. ASSIGN_PATIENTS, the permission that
    already governs which doctor may see a patient."""
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.is_provisional:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    try:
        await assignment_service.change_doctor(db, patient, payload.doctor_id, actor)
    except assignment_service.NotADoctorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return await _out(db, patient)
