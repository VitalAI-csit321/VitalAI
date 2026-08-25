from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission
from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentOut,
    AppointmentReschedule,
)
from app.services import appointment_service
from app.services.appointment_service import (
    AppointmentStateError,
    CaseNotFoundError,
    DoctorNotFoundError,
    DoctorPatientAccessError,
    NotADoctorError,
    SlotTakenError,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _own_calendar_scope(actor: User) -> UUID | None:
    return actor.id if actor.role == UserRole.DOCTOR else None


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def book_appointment_endpoint(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    if actor.role == UserRole.DOCTOR and payload.doctor_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctors may only book appointments on their own calendar",
        )

    try:
        return await appointment_service.book_appointment(
            db, payload.doctor_id, payload.case_id, payload.time_slot, actor
        )
    except (DoctorNotFoundError, CaseNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotADoctorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SlotTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DoctorPatientAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("", response_model=AppointmentListResponse)
async def list_appointments_endpoint(
    doctor_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    own_scope = _own_calendar_scope(actor)
    effective_doctor_id = own_scope if own_scope is not None else doctor_id
    items, total = await appointment_service.list_appointments(
        db, actor, doctor_id=effective_doctor_id, limit=limit, offset=offset
    )
    return AppointmentListResponse(
        items=[AppointmentOut.model_validate(a) for a in items], total=total
    )


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule_appointment_endpoint(
    appointment_id: UUID,
    payload: AppointmentReschedule,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    try:
        appointment = await appointment_service.reschedule_appointment(
            db, appointment_id, payload.time_slot, actor, _own_calendar_scope(actor)
        )
    except SlotTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AppointmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appointment


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment_endpoint(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    try:
        appointment = await appointment_service.cancel_appointment(
            db, appointment_id, actor, _own_calendar_scope(actor)
        )
    except AppointmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appointment
