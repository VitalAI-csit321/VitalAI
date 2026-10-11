"""A patient's own upcoming appointment, by email: say when it is, or cancel it.

Reached from graph.route_identity when the reply gate reads the email as being
about an appointment the sender already has. Before this, "when is my
appointment?" was a booking request because its category said appointment
(2026-10-11 test run). Moving one is the booking conversation's job; this
module only finds which appointment is meant.

Amin's calls (2026-10-11): the sender is trusted as the patient only when the
email comes from the address on exactly one patient record, and the agent
cancels by itself when one appointment can be meant and it is more than
MIN_NOTICE away. Everything else is the front desk's.
"""

from __future__ import annotations

import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.base import utcnow
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.user import User
from app.services import appointment_service, booking_service
from app.services.audit_service import record_event

# The clinic's late-cancellation fee starts here (02_Policies_and_FAQ.md), and
# whether to charge it is a person's decision.
MIN_NOTICE = timedelta(hours=24)

_SIGN_OFF = "\n\nKind regards,\nThe clinic team"
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


async def patient_for_sender(db: AsyncSession, sender: str) -> Patient | None:
    """The one registered patient whose record has this address. A shared
    family inbox (two records) is nobody: the email does not say which."""
    rows = (
        (
            await db.execute(
                select(Patient).where(
                    func.lower(func.trim(Patient.email)) == sender.strip().casefold(),
                    Patient.purged_at.is_(None),
                    Patient.is_provisional.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    return rows[0] if len(rows) == 1 else None


async def upcoming(db: AsyncSession, patient_id: UUID) -> list[Appointment]:
    return list(
        (
            await db.execute(
                select(Appointment)
                .join(IntakeCase, IntakeCase.id == Appointment.case_id)
                .where(
                    IntakeCase.patient_id == patient_id,
                    Appointment.time_slot > utcnow(),
                    Appointment.status.in_(
                        [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
                    ),
                )
                .order_by(Appointment.time_slot)
            )
        )
        .scalars()
        .all()
    )


def target(
    text: str, appointments: list[Appointment], *, moving: bool = False
) -> Appointment | None:
    """The appointment the email means, or None when that is not certain.

    moving: a day in the email is as likely the day they want as the day
    they have ("anything on Thursday instead?" was read as "my Thursday
    appointment"), so only a patient with one appointment has an answer.

    ponytail: weekday names and "the 14th" only, matched as words. "Next
    week's one" or "the one with Dr Osei" is None, so it is asked about; give
    the reply gate a date field if that turns out to be common.
    """
    if moving:
        return appointments[0] if len(appointments) == 1 else None
    low = text.lower()
    named = []
    for appointment in appointments:
        local = appointment_service.clinic_date(appointment.time_slot)
        if re.search(rf"\b{local:%A}\b".lower(), low) or re.search(
            rf"\b{local.day}(st|nd|rd|th)\b", low
        ):
            named.append(appointment)
    if named:
        return named[0] if len(named) == 1 else None
    # A day was named and none of theirs is on it: not the one they mean.
    if any(re.search(rf"\b{day}\b", low) for day in _WEEKDAYS):
        return None
    return appointments[0] if len(appointments) == 1 else None


async def describe(db: AsyncSession, appointment: Appointment) -> str:
    """ "Tuesday 1 September at 8:00am with Dr Priya Menon"."""
    doctor = await db.get(User, appointment.doctor_id)
    return slot_text(appointment, doctor.full_name if doctor else "the doctor")


def slot_text(appointment: Appointment, doctor_name: str) -> str:
    return (
        f"{booking_service.format_slot(appointment.time_slot)} with "
        f"{booking_service.titled(doctor_name)}"
    )


def _hi(name: str | None) -> str:
    return f"Hi {name.split()[0]}," if name else "Hello,"


def when_text(name: str | None, described: list[str]) -> str:
    if not described:
        body = (
            "We could not find an upcoming appointment on your record. If you would "
            "like to book one, reply with the day you would like to come in."
        )
    elif len(described) == 1:
        body = f"Your next appointment is on {described[0]}."
    else:
        body = "Your upcoming appointments are:\n" + "\n".join(f"- {d}" for d in described)
    return f"{_hi(name)}\n\n{body}" + _SIGN_OFF


def which_text(name: str | None, described: list[str]) -> str:
    if len(described) == 1:
        return (
            f"{_hi(name)}\n\nThe appointment we have for you is on {described[0]}. Is that "
            "the one you mean? Please reply to confirm." + _SIGN_OFF
        )
    return (
        f"{_hi(name)}\n\nYou have more than one upcoming appointment:\n"
        + "\n".join(f"- {d}" for d in described)
        + "\n\nPlease reply with the day of the one you mean."
        + _SIGN_OFF
    )


def cancelled_text(name: str | None, described: str) -> str:
    return (
        f"{_hi(name)}\n\nYour appointment on {described} has been cancelled. If you would "
        "like another time, reply with the day you would like to come in." + _SIGN_OFF
    )


def late_text(name: str | None, described: str) -> str:
    return (
        f"{_hi(name)}\n\nWe have received your request to cancel your appointment on "
        f"{described}. As it is less than 24 hours away, the front desk will confirm it "
        "with you." + _SIGN_OFF
    )


MOVE_REASON = (
    "The patient asked by email to move an appointment and has more than one coming "
    "up. They were sent the list and told the front desk will be in touch. Find out "
    "which one and move it."
)


def move_staff_text(name: str | None, described: list[str]) -> str:
    return (
        f"{_hi(name)}\n\nWe have received your request to change an appointment. You have "
        "more than one coming up:\n"
        + "\n".join(f"- {d}" for d in described)
        + "\n\nThe front desk will be in touch to move the right one."
        + _SIGN_OFF
    )


def late_reason(appointment: Appointment, doctor_name: str) -> str:
    """What the front desk's Review Queue item says."""
    return (
        f"The patient asked by email to cancel their appointment on "
        f"{slot_text(appointment, doctor_name)}, which is inside the notice period. "
        "They were told the front desk will confirm it. Cancel it and decide on the fee."
    )


def is_late(appointment: Appointment) -> bool:
    return appointment.time_slot - utcnow() < MIN_NOTICE


async def cancel(db: AsyncSession, appointment: Appointment, actor: User) -> None:
    await appointment_service.cancel_appointment(
        db,
        appointment.id,
        actor,
        None,
        cancel_reason="Cancelled by the agent at the patient's emailed request.",
        # The reply to their email is the notice.
        notify_patient=False,
    )
    await record_event(
        db,
        actor=actor,
        case_id=appointment.case_id,
        action="agent.appointment_cancelled",
        details={"appointment_id": str(appointment.id)},
    )
    await db.commit()
