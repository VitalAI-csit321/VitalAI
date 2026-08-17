from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scoping import assigned_patient_ids_subquery, is_assigned
from app.models.appointment import Appointment, AppointmentStatus
from app.models.case import IntakeCase
from app.models.user import User, UserRole
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

async def book_appointment(
    db: AsyncSession, doctor_id: UUID, case_id: UUID, time_slot: datetime, actor: User
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
        status=AppointmentStatus.CONFIRMED,
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
    db: AsyncSession, actor: User, doctor_id: UUID | None = None, limit: int = 20, offset: int = 0
) -> tuple[list[Appointment], int]:
        query = select(Appointment)
        count_query = select(func.count()).select_from(Appointment)

        if doctor_id is not None:
            query = query.where(Appointment.doctor_id == doctor_id)
            count_query = count_query.where(Appointment.doctor_id == doctor_id)

        if actor.role == UserRole.DOCTOR:
            assigned_patient_ids = assigned_patient_ids_subquery(actor.id)

            query = query.join(
                IntakeCase,
                Appointment.case_id == IntakeCase.id,
            ).where(IntakeCase.patient_id.in_(assigned_patient_ids))

            count_query = count_query.join(
                IntakeCase,
                Appointment.case_id == IntakeCase.id,
            ).where(IntakeCase.patient_id.in_(assigned_patient_ids))

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
