from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import ASSIGN_PATIENTS
from app.database import get_db
from app.models.user import User
from app.schemas.assignment import AssignmentCreate, AssignmentOut
from app.services import assignment_service
from app.services.assignment_service import (
    AssignmentExistsError,
    DoctorNotFoundError,
    NotADoctorError,
    PatientNotFoundError,
)

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post("", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
async def create_assignment_endpoint(
    payload: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(ASSIGN_PATIENTS)),
):
    try:
        return await assignment_service.assign_patient(
            db, payload.doctor_id, payload.patient_id, actor
        )
    except (DoctorNotFoundError, PatientNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotADoctorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except AssignmentExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{doctor_id}/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment_endpoint(
    doctor_id: UUID,
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(ASSIGN_PATIENTS)),
):
    deleted = await assignment_service.unassign_patient(db, doctor_id, patient_id, actor)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")


@router.get("", response_model=list[AssignmentOut])
async def list_assignments_endpoint(
    doctor_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(ASSIGN_PATIENTS)),
):
    return await assignment_service.list_assignments(db, doctor_id)
