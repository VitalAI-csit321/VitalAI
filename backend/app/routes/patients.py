from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import REGISTER_PATIENT, VIEW_RECORDS_GENERAL
from app.database import get_db
from app.models.patient import Patient, PatientStatus
from app.models.user import User, UserRole
from app.schemas.patient import (
    PatientCounts,
    PatientCreate,
    PatientListResponse,
    PatientOut,
    PatientUpdate,
)
from app.services import patient_service

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient_endpoint(
    payload: PatientCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(REGISTER_PATIENT)),
):
    return await patient_service.create_patient(db, payload, actor)


@router.get("", response_model=PatientListResponse)
async def list_patients_endpoint(
    search: str | None = None,
    status: PatientStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    doctor_id = actor.id if actor.role == UserRole.DOCTOR else None
    items, total, counts = await patient_service.list_patients(
        db, search=search, status=status, limit=limit, offset=offset, doctor_id=doctor_id
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
    patient = await patient_service.get_patient_by_id(db, patient_id, doctor_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


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
    return await patient_service.update_patient(db, patient, payload, actor)
