from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission
from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR
from app.database import get_db
from app.models.appointment import AppointmentStatus, AppointmentType
from app.models.user import User, UserRole
from app.schemas.appointment import (
    AppointmentCancel,
    AppointmentCreate,
    AppointmentDetailOut,
    AppointmentListResponse,
    AppointmentOut,
    AppointmentReschedule,
    AppointmentUpdate,
    AvailabilityOut,
    CalendarMarkerOut,
    CalendarMonthOut,
    DayViewOut,
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
        created = await appointment_service.book_appointment_series(db, payload, actor)
        return await appointment_service.serialize_appointment(db, created[0])
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
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    appointment_type: AppointmentType | None = None,
    status_filter: AppointmentStatus | None = Query(default=None, alias="status"),
    search: str | None = None,
    # le=200, not the usual 100: CalendarPage's week view (limit: 200 in
    # frontend/frontend/src/pages/CalendarPage.tsx) legitimately needs to fetch
    # a whole week's appointments across every doctor in one page.
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    own_scope = _own_calendar_scope(actor)
    effective_doctor_id = own_scope if own_scope is not None else doctor_id
    items, total = await appointment_service.list_appointments(
        db,
        actor,
        doctor_id=effective_doctor_id,
        date_from=date_from,
        date_to=date_to,
        appointment_type=appointment_type,
        status=status_filter,
        search=search,
        limit=limit,
        offset=offset,
    )
    return AppointmentListResponse(
        items=await appointment_service.serialize_many(db, items), total=total
    )


@router.get("/calendar", response_model=CalendarMonthOut)
async def get_calendar_endpoint(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    doctor_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    own_scope = _own_calendar_scope(actor)
    return await appointment_service.get_calendar_month(
        db, actor, year, month, own_scope if own_scope is not None else doctor_id
    )


@router.get("/calendar/markers", response_model=list[CalendarMarkerOut])
async def get_calendar_markers_endpoint(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    doctor_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    own_scope = _own_calendar_scope(actor)
    return await appointment_service.get_calendar_markers(
        db, actor, year, month, own_scope if own_scope is not None else doctor_id
    )


@router.get("/day", response_model=DayViewOut)
async def get_day_endpoint(
    day: date = Query(alias="date"),
    doctor_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    own_scope = _own_calendar_scope(actor)
    return await appointment_service.get_day_view(
        db, actor, day, own_scope if own_scope is not None else doctor_id
    )


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability_endpoint(
    doctor_id: UUID,
    day: date = Query(alias="date"),
    slot_minutes: int = Query(default=30, ge=5, le=240),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    own_scope = _own_calendar_scope(actor)
    if own_scope is not None and own_scope != doctor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctors may only view their own calendar's availability",
        )
    return await appointment_service.get_availability(db, actor, doctor_id, day, slot_minutes)


@router.get("/{appointment_id}", response_model=AppointmentDetailOut)
async def get_appointment_endpoint(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    detail = await appointment_service.get_appointment_detail(
        db, actor, appointment_id, _own_calendar_scope(actor)
    )
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return detail


@router.patch("/{appointment_id}", response_model=AppointmentOut)
async def update_appointment_endpoint(
    appointment_id: UUID,
    payload: AppointmentUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    if (
        actor.role == UserRole.DOCTOR
        and payload.doctor_id is not None
        and payload.doctor_id != actor.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctors may only reassign appointments to their own calendar",
        )

    try:
        appointment = await appointment_service.update_appointment(
            db, appointment_id, payload, actor, _own_calendar_scope(actor)
        )
    except SlotTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AppointmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DoctorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotADoctorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return await appointment_service.serialize_appointment(db, appointment)


@router.post("/{appointment_id}/complete", response_model=AppointmentOut)
async def complete_appointment_endpoint(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    try:
        appointment = await appointment_service.complete_appointment(
            db, appointment_id, actor, _own_calendar_scope(actor)
        )
    except AppointmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return await appointment_service.serialize_appointment(db, appointment)


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
    return await appointment_service.serialize_appointment(db, appointment)


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment_endpoint(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
    payload: AppointmentCancel | None = Body(None),
):
    try:
        appointment = await appointment_service.cancel_appointment(
            db,
            appointment_id,
            actor,
            _own_calendar_scope(actor),
            cancel_reason=payload.cancel_reason if payload else None,
            notify_patient=payload.notify_patient if payload else True,
        )
    except AppointmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return await appointment_service.serialize_appointment(db, appointment)
