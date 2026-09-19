"""Proposing appointment times to a patient we have identified (build spec §10).

Proposes and stops. Nothing here books anything: `book_appointment` keeps
exactly one caller in the whole app, and a human confirming a time is the only
path into a real booking (RBAC report §11, invariant 2).

Every time in the draft is rendered in clinic local time, and the draft itself
is a template, not a generation. What time the clinic told a patient to turn up
is not a thing a model may decide.
"""

import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assignment import DoctorPatientAssignment
from app.models.user import User
from app.services import appointment_service

BRANCH = "booking"

# Two working weeks. Long enough to find something in a normally busy diary,
# short enough that a proposed time is still meaningful when a human approves
# the reply tomorrow.
HORIZON_DAYS = 14
MAX_PROPOSALS = 3

NO_DOCTOR_REASON = (
    "This patient has no doctor assigned, so no appointment time was proposed. "
    "Assign a doctor, then reply with times."
)
NO_SLOTS_REASON = (
    f"No appointment time was free with this patient's doctor in the next {HORIZON_DAYS} "
    "days, so nothing was proposed. Offer a time by hand or extend the diary."
)


async def doctor_for_patient(db: AsyncSession, patient_id: UUID) -> tuple[UUID, str] | None:
    """The patient's longest-standing active doctor, or None if they have none.

    Proposing a time with a doctor who has no care relationship to the patient
    is worse than proposing nothing, so "none" is an answer, not a fallback.
    """
    row = (
        await db.execute(
            select(DoctorPatientAssignment.doctor_id, User.full_name)
            .join(User, User.id == DoctorPatientAssignment.doctor_id)
            .where(
                DoctorPatientAssignment.patient_id == patient_id,
                User.is_active.is_(True),
            )
            .order_by(DoctorPatientAssignment.assigned_at)
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def find_slots(
    db: AsyncSession,
    actor: User,
    doctor_id: UUID,
    *,
    from_date: date | None = None,
    count: int = MAX_PROPOSALS,
    horizon_days: int = HORIZON_DAYS,
) -> list[datetime]:
    """The next `count` free slots, scanning clinic-local days from tomorrow.

    Fewer than `count` is a real answer: an empty list means the diary is full
    for the whole horizon, and two means propose two. The list is never padded.

    Weekends are skipped, the same rule appointment_suggestion_service already
    applies when staff ask for suggested times.
    """
    if from_date is None:
        from_date = appointment_service.clinic_date(datetime.now(UTC)) + timedelta(days=1)
    found: list[datetime] = []
    for offset in range(horizon_days):
        if len(found) >= count:
            break
        day = from_date + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        availability = await appointment_service.get_availability(
            db, actor, doctor_id, day, settings.default_appointment_duration_minutes
        )
        for slot in availability.slots:
            if len(found) >= count:
                break
            if slot.available:
                found.append(slot.start)
    return found


def format_slot(instant: datetime) -> str:
    """ "Tuesday 1 September at 8:00am", in clinic local time."""
    local = instant.astimezone(ZoneInfo(settings.clinic_timezone))
    hour = local.hour % 12 or 12
    meridiem = "am" if local.hour < 12 else "pm"
    return f"{local:%A} {local.day} {local:%B} at {hour}:{local:%M}{meridiem}"


def _titled(doctor_name: str) -> str:
    """Doctor names are stored both ways: seeded staff without the title, the
    demo corpus's doctors as "Dr Aisha Rahman". Title them once."""
    return doctor_name if re.match(r"dr\.?\s", doctor_name, re.IGNORECASE) else f"Dr {doctor_name}"


def draft_booking_reply(*, name: str | None, doctor_name: str, slots: list[str]) -> str:
    """The proposal. A template, never a generated one, and it promises nothing:
    the times are offered, the patient picks, a human confirms."""
    offered = "\n".join(f"- {format_slot(datetime.fromisoformat(s))}" for s in slots)
    times = "this time" if len(slots) == 1 else "one of these times"
    return (
        f"Hi {name.split()[0] if name else 'there'},\n\n"
        "Thank you for getting in touch about an appointment. "
        f"{_titled(doctor_name)} has the following available:\n\n"
        f"{offered}\n\n"
        f"Please reply and let us know if {times} suits you and we will confirm it. "
        "Nothing has been booked yet.\n\n"
        "Kind regards,\nThe clinic team"
    )
