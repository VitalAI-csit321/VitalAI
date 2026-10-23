"""A patient's own upcoming appointment, by email: say when it is, or cancel it.

Reached from graph.route_identity when the reply gate reads the email as being
about an appointment the sender already has. Before this, "when is my
appointment?" was a booking request because its category said appointment.
Moving one is the booking conversation's job; this
module only finds which appointment is meant.

Deliberate choices: the sender is taken to be the patient only when the
email comes from the address on exactly one patient record, and the agent
cancels by itself when one appointment can be meant and it is more than
MIN_NOTICE away. Everything else is the front desk's.

A From address can be forged, so that match proves little by itself. Two rules
follow (from a security review of the first version). Nothing here is sent
as a reply, which would follow a forged email's Reply-To: it goes as a new
email to the address on the record. And a cancel or move is not carried out
on the email that asks: that email earns a one-time code, sent to the same
address, and only a reply carrying the code is acted on.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
    """The one patient whose record has this address. A shared family inbox
    (two records) is nobody: the email does not say which.

    Provisional records count. A first-visit patient is provisional until
    they attend, and the appointment they booked by email is theirs to ask
    about and change: left out, their reply to "if you need to change it,
    reply to this email" was answered with a request to verify who they are.
    """
    rows = (
        (
            await db.execute(
                select(Patient).where(
                    func.lower(func.trim(Patient.email)) == sender.strip().casefold(),
                    Patient.purged_at.is_(None),
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

    Limitation: weekday names and "the 14th" only, matched as words. "Next
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


def confirmation_code(conversation_id: UUID, appointment_id: UUID, action: str) -> str:
    """Six digits for one request to cancel or move one appointment.

    Derived, not stored: an HMAC of the request under the app's secret, so
    there is no column to add and nothing to read out of the database. It is
    spent when the conversation leaves AWAITING_CONFIRMATION.
    """
    digest = hmac.new(
        settings.jwt_secret_key.encode(),
        f"{conversation_id}:{appointment_id}:{action}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{int(digest[:12], 16) % 1_000_000:06d}"


# "That was not me", with the code quoted underneath by the mail client.
_DECLINES = re.compile(r"\b(no|not|never|didn'?t|don'?t|wrong|mistake)\b", re.IGNORECASE)


def confirmed_action(written: str, conversation_id: UUID, appointment_id: UUID) -> str | None:
    """ "cancel" or "move" when what the sender wrote carries that request's
    code and does not read as a refusal; None otherwise. written is the new
    text of the reply, never the quoted email under it, which holds the code.

    Exactly one six-digit number, or it is not an answer: a forged reply
    cannot see the code, but it could list thousands and have it among them.
    One email is one guess, and the caller spends the request on a miss.
    """
    if _DECLINES.search(written):
        return None
    # re.ASCII: \d otherwise matches every script's digits, and a code is
    # only ever 0-9. Compared as bytes, which compare_digest takes whatever
    # the text holds; on a str it raises for anything outside ASCII.
    candidates = set(re.findall(r"\b\d{6}\b", written, re.ASCII))
    if len(candidates) != 1:
        return None
    (candidate,) = candidates
    for action in ("cancel", "move"):
        code = confirmation_code(conversation_id, appointment_id, action)
        if hmac.compare_digest(candidate.encode(), code.encode()):
            return action
    return None


def confirm_text(name: str | None, described: str, action: str, code: str) -> str:
    asked = "cancel" if action == "cancel" else "change"
    then = (
        "and we will cancel it."
        if action == "cancel"
        else "and we will send you the times available."
    )
    return (
        f"{_hi(name)}\n\nWe received an email asking to {asked} your appointment on "
        f"{described}.\n\nTo confirm, reply to this email with the code {code} {then} "
        "Nothing has been changed yet.\n\n"
        "If you did not ask for this, you do not need to do anything." + _SIGN_OFF
    )


UNCONFIRMED_REASON = (
    "The patient was sent a code to confirm cancelling or changing an appointment, and "
    "their reply did not confirm it. Nothing was changed. Check with the patient."
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
