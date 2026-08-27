import calendar as _calendar
import secrets
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scoping import assigned_patient_ids_subquery, is_assigned
from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.schemas.appointment import (
    AppointmentOut,
    CalendarDayCell,
    CalendarMarkerOut,
    CalendarMonthOut,
    CalendarStats,
)
from app.services.audit_service import record_event


class DoctorNotFoundError(Exception):
    """Raised when doctor_id doesn't reference an existing user."""


class NotADoctorError(Exception):
    """Raised when doctor_id references a user whose role isn't DOCTOR."""


class CaseNotFoundError(Exception):
    """Raised when case_id doesn't reference an existing intake case."""


class SlotTakenError(Exception):
    """Raised when (doctor_id, time_slot) is already booked."""


class AppointmentStateError(Exception):
    """Raised when rescheduling/cancelling an appointment in an illegal state."""


class DoctorPatientAccessError(Exception):
    """Raised when a Doctor tries to manage a patient who is not assigned to them."""


_REFERENCE_CODE_ATTEMPTS = 10


async def _generate_unique_reference_code(db: AsyncSession) -> str:
    for _ in range(_REFERENCE_CODE_ATTEMPTS):
        candidate = f"APT-{secrets.token_hex(3).upper()}"
        existing = await db.execute(
            select(Appointment.id).where(Appointment.reference_code == candidate)
        )
        if existing.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError(
        "Could not generate a unique appointment reference after "
        f"{_REFERENCE_CODE_ATTEMPTS} attempts"
    )


async def book_appointment(
    db: AsyncSession,
    doctor_id: UUID,
    case_id: UUID,
    time_slot: datetime,
    actor: User,
    duration_minutes: int = 30,
    appointment_type: AppointmentType = AppointmentType.OTHER,
    location: str | None = None,
    reason: str | None = None,
    internal_notes: str | None = None,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    notify_patient: bool = True,
    notify_provider: bool = True,
    series_id: UUID | None = None,
) -> Appointment:
    # Validated up front so a bogus doctor_id/case_id can't slip through as a
    # "successful" booking, and so the later IntegrityError catch can only
    # mean one thing: the (doctor_id, time_slot) slot is already taken.
    doctor = await db.get(User, doctor_id)
    if doctor is None:
        raise DoctorNotFoundError(f"No user with id {doctor_id}")
    if doctor.role != UserRole.DOCTOR:
        raise NotADoctorError(f"User {doctor_id} has role '{doctor.role.value}', not 'doctor'")
    case = await db.get(IntakeCase, case_id)
    if case is None:
        raise CaseNotFoundError(f"No case with id {case_id}")

    if actor.role == UserRole.DOCTOR:
        if case.patient_id is None or not await is_assigned(db, actor.id, case.patient_id):
            raise DoctorPatientAccessError(
                f"Patient for case {case_id} is not assigned to doctor {actor.id}"
            )

    appointment = Appointment(
        doctor_id=doctor_id,
        case_id=case_id,
        time_slot=time_slot,
        duration_minutes=duration_minutes,
        appointment_type=appointment_type,
        location=location,
        reason=reason,
        internal_notes=internal_notes,
        status=status,
        reference_code=await _generate_unique_reference_code(db),
        notify_patient=notify_patient,
        notify_provider=notify_provider,
        series_id=series_id,
    )
    db.add(appointment)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise SlotTakenError(
            f"Doctor {doctor_id} already has an appointment at {time_slot}"
        ) from exc

    await record_event(
        db,
        case_id=case_id,
        actor=actor,
        action="appointment.booked",
        details={
            "appointment_id": str(appointment.id),
            "doctor_id": str(doctor_id),
            "time_slot": time_slot.isoformat(),
        },
    )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def list_appointments(
    db: AsyncSession,
    actor: User,
    doctor_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    appointment_type: AppointmentType | None = None,
    status: AppointmentStatus | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Appointment], int]:
    query = select(Appointment)
    count_query = select(func.count()).select_from(Appointment)

    def apply(q, is_count: bool):
        if doctor_id is not None:
            q = q.where(Appointment.doctor_id == doctor_id)
        if date_from is not None:
            q = q.where(Appointment.time_slot >= date_from)
        if date_to is not None:
            q = q.where(Appointment.time_slot < date_to)
        if appointment_type is not None:
            q = q.where(Appointment.appointment_type == appointment_type)
        if status is not None:
            q = q.where(Appointment.status == status)
        if search or actor.role == UserRole.DOCTOR:
            q = q.join(IntakeCase, Appointment.case_id == IntakeCase.id)
        if search:
            q = q.outerjoin(Patient, IntakeCase.patient_id == Patient.id).where(
                Patient.name.ilike(f"%{search}%")
            )
        if actor.role == UserRole.DOCTOR:
            q = q.where(IntakeCase.patient_id.in_(assigned_patient_ids_subquery(actor.id)))
        return q

    query = apply(query, False)
    count_query = apply(count_query, True)

    items_result = await db.execute(
        query.order_by(Appointment.time_slot.asc()).limit(limit).offset(offset)
    )
    items = list(items_result.scalars().all())

    total = (await db.execute(count_query)).scalar_one()

    return items, total


async def _get_scoped(
    db: AsyncSession,
    appointment_id: UUID,
    actor: User,
    scoped_doctor_id: UUID | None,
) -> Appointment | None:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        return None

    if scoped_doctor_id is not None and appointment.doctor_id != scoped_doctor_id:
        return None

    if actor.role == UserRole.DOCTOR:
        case = await db.get(IntakeCase, appointment.case_id)
        if case is None or case.patient_id is None:
            return None

        if not await is_assigned(db, actor.id, case.patient_id):
            return None

    return appointment


async def reschedule_appointment(
    db: AsyncSession,
    appointment_id: UUID,
    new_time_slot: datetime,
    actor: User,
    scoped_doctor_id: UUID | None,
) -> Appointment | None:
    appointment = await _get_scoped(db, appointment_id, actor, scoped_doctor_id)
    if appointment is None:
        return None
    if appointment.status == AppointmentStatus.CANCELLED:
        raise AppointmentStateError("Cannot reschedule a cancelled appointment")

    doctor_id = appointment.doctor_id
    appointment.time_slot = new_time_slot
    try:
        await db.flush()
    except IntegrityError as exc:
        # doctor_id was captured before flush: rollback() expires the ORM
        # object, so reading appointment.doctor_id here would trigger a lazy
        # load outside the async greenlet context and raise MissingGreenlet.
        await db.rollback()
        raise SlotTakenError(
            f"Doctor {doctor_id} already has an appointment at {new_time_slot}"
        ) from exc

    await record_event(
        db,
        case_id=appointment.case_id,
        actor=actor,
        action="appointment.rescheduled",
        details={"appointment_id": str(appointment_id), "time_slot": new_time_slot.isoformat()},
    )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def cancel_appointment(
    db: AsyncSession, appointment_id: UUID, actor: User, scoped_doctor_id: UUID | None
) -> Appointment | None:
    appointment = await _get_scoped(db, appointment_id, actor, scoped_doctor_id)
    if appointment is None:
        return None
    if appointment.status == AppointmentStatus.CANCELLED:
        raise AppointmentStateError("Appointment is already cancelled")

    appointment.status = AppointmentStatus.CANCELLED
    await record_event(
        db,
        case_id=appointment.case_id,
        actor=actor,
        action="appointment.cancelled",
        details={"appointment_id": str(appointment_id)},
    )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def serialize_appointment(db: AsyncSession, appointment: Appointment) -> AppointmentOut:
    """Attach the three joined labels and the derived end_time.

    doctor_name / patient_name / patient_mrn are joined per call rather than
    stored: storing them creates a second source of truth that drifts the
    first time a user or patient is renamed.
    """
    return (await serialize_many(db, [appointment]))[0]


async def serialize_many(
    db: AsyncSession, appointments: list[Appointment]
) -> list[AppointmentOut]:
    if not appointments:
        return []

    doctor_ids = {a.doctor_id for a in appointments}
    case_ids = {a.case_id for a in appointments}

    doctors = (
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(doctor_ids))))
        .all()
    )
    doctor_names = {row[0]: row[1] for row in doctors}

    patient_rows = (
        await db.execute(
            select(IntakeCase.id, Patient.name, Patient.mrn)
            .select_from(IntakeCase)
            .outerjoin(Patient, IntakeCase.patient_id == Patient.id)
            .where(IntakeCase.id.in_(case_ids))
        )
    ).all()
    patients_by_case = {row[0]: (row[1], row[2]) for row in patient_rows}

    out: list[AppointmentOut] = []
    for a in appointments:
        patient_name, patient_mrn = patients_by_case.get(a.case_id, (None, None))
        out.append(
            AppointmentOut(
                id=a.id,
                case_id=a.case_id,
                doctor_id=a.doctor_id,
                time_slot=a.time_slot,
                end_time=a.end_time,
                duration_minutes=a.duration_minutes,
                appointment_type=a.appointment_type,
                location=a.location,
                reason=a.reason,
                internal_notes=a.internal_notes,
                status=a.status,
                reference_code=a.reference_code,
                notify_patient=a.notify_patient,
                notify_provider=a.notify_provider,
                series_id=a.series_id,
                created_at=a.created_at,
                updated_at=a.updated_at,
                doctor_name=doctor_names.get(a.doctor_id),
                patient_name=patient_name,
                patient_mrn=patient_mrn,
            )
        )
    return out


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    first = datetime(year, month, 1, tzinfo=UTC)
    last_day = _calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, tzinfo=UTC) + timedelta(days=1)
    return first, end


def _stats(appointments: list[Appointment]) -> CalendarStats:
    today = datetime.now(UTC).date()
    return CalendarStats(
        scheduled=sum(
            1
            for a in appointments
            if a.status in (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)
        ),
        pending_confirmation=sum(
            1 for a in appointments if a.status == AppointmentStatus.PENDING
        ),
        confirmed_today=sum(
            1
            for a in appointments
            if a.status == AppointmentStatus.CONFIRMED and a.time_slot.date() == today
        ),
        cancellations=sum(1 for a in appointments if a.status == AppointmentStatus.CANCELLED),
    )


async def _appointments_in_range(
    db: AsyncSession,
    actor: User,
    start: datetime,
    end: datetime,
    doctor_id: UUID | None,
) -> list[Appointment]:
    # limit is deliberately high: a month view must not paginate.
    items, _ = await list_appointments(
        db, actor, doctor_id=doctor_id, date_from=start, date_to=end, limit=1000
    )
    return items


async def get_calendar_month(
    db: AsyncSession, actor: User, year: int, month: int, doctor_id: UUID | None = None
) -> CalendarMonthOut:
    start, end = _month_bounds(year, month)
    appointments = await _appointments_in_range(db, actor, start, end, doctor_id)

    # Serialize the whole month in ONE pass, then group. Calling serialize_many
    # per day would fire two extra queries per day (about 60 for a month).
    serialized = await serialize_many(db, appointments)
    by_day: dict[date, list] = defaultdict(list)
    for item in serialized:
        ts = item.time_slot
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        by_day[ts.astimezone(UTC).date()].append(item)

    days: list[CalendarDayCell] = []
    for day_number in range(1, _calendar.monthrange(year, month)[1] + 1):
        day = date(year, month, day_number)
        day_appointments = by_day.get(day, [])
        days.append(
            CalendarDayCell(
                date=day.isoformat(),
                appointments=day_appointments,
                total=len(day_appointments),
            )
        )

    return CalendarMonthOut(year=year, month=month, stats=_stats(appointments), days=days)


async def get_calendar_markers(
    db: AsyncSession, actor: User, year: int, month: int, doctor_id: UUID | None = None
) -> list[CalendarMarkerOut]:
    start, end = _month_bounds(year, month)
    appointments = await _appointments_in_range(db, actor, start, end, doctor_id)

    counts: dict[date, int] = defaultdict(int)
    for a in appointments:
        ts = a.time_slot
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        counts[ts.astimezone(UTC).date()] += 1
    return [
        CalendarMarkerOut(date=day.isoformat(), count=count)
        for day, count in sorted(counts.items())
    ]
