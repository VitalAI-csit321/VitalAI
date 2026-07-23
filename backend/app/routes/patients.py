from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import REGISTER_PATIENT, VIEW_RECORDS_GENERAL
from app.database import get_db
from app.models.patient import PatientStatus
from app.models.user import User
from app.schemas.patient import PatientCounts, PatientCreate, PatientListResponse, PatientOut
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
    _: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    items, total, counts = await patient_service.list_patients(
        db, search=search, status=status, limit=limit, offset=offset
    )
    return PatientListResponse(
        items=[PatientOut.model_validate(p) for p in items],
        total=total,
        counts=PatientCounts(**counts),
    )
