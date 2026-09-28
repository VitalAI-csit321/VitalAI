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
from functools import cache
from uuid import UUID
from zoneinfo import ZoneInfo

import holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assignment import DoctorPatientAssignment
from app.models.user import User, UserRole
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


@cache
def _holidays(region: str, year: int) -> holidays.HolidayBase:
    return holidays.country_holidays("AU", subdiv=region, years=year)


def is_clinic_day(day: date) -> bool:
    """A weekday that is not a public holiday in the clinic's state. The
    clinic is closed on those, and email booking offered Labour Day slots."""
    return day.weekday() < 5 and day not in _holidays(settings.clinic_holiday_region, day.year)


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
        if not is_clinic_day(day):
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


def titled(doctor_name: str) -> str:
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
        f"{titled(doctor_name)} has the following available:\n\n"
        f"{offered}\n\n"
        f"Please reply and let us know if {times} suits you and we will confirm it. "
        "Nothing has been booked yet.\n\n"
        "Kind regards,\nThe clinic team"
    )


# --- the email booking conversation (email_conversation_service) ---------------

# Enough to choose from without a wall of times in an email.
MAX_SLOTS_PER_DAY = 6
# How far either side of the requested day to look when it is full.
NEAREST_SPAN_DAYS = 14
NEAREST_DAYS_OFFERED = 2

Doctor = tuple[UUID, str]
Slot = tuple[datetime, UUID, str]


async def doctor_pool(
    db: AsyncSession,
    patient_id: UUID | None,
    *,
    doctor_name: str | None = None,
    specialisation: str | None = None,
) -> tuple[list[Doctor], list[Doctor]] | None:
    """(first choice, fallback). None when the patient asked for a doctor or
    specialisation nobody active matches: that is a question for staff, not a
    reason to offer someone else.

    Default: the patient's own doctor first, any doctor as the fallback; with
    no assigned doctor, any doctor. Every active doctor counts as a GP here,
    because nothing in the data says otherwise (User.department is empty for
    the seeded doctors, so a specialisation request finds nobody).
    """
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.department)
            .where(User.role == UserRole.DOCTOR, User.is_active.is_(True))
            .order_by(User.full_name)
        )
    ).all()
    if doctor_name:
        wanted = [
            t for t in re.findall(r"[a-z'-]+", doctor_name.casefold()) if t not in {"dr", "doctor"}
        ]
        picked = [(i, n) for i, n, _ in rows if wanted and all(t in n.casefold() for t in wanted)]
        return (picked, []) if picked else None
    if specialisation:
        spec = specialisation.casefold().strip()
        picked = [(i, n) for i, n, dept in rows if dept and spec in dept.casefold()]
        return (picked, []) if picked else None
    everyone = [(i, n) for i, n, _ in rows]
    assigned = await doctor_for_patient(db, patient_id) if patient_id else None
    return ([assigned], everyone) if assigned else (everyone, [])


async def free_on_day(
    db: AsyncSession,
    actor: User,
    doctors: list[Doctor],
    day: date,
    *,
    part_of_day: str | None = None,
) -> list[Slot]:
    """Every free start time that day across the doctors, earliest first, one
    doctor per time (the first in `doctors` order wins, so an assigned doctor
    is preferred). Weekends and times already past are never free."""
    if not is_clinic_day(day):
        return []
    tz = ZoneInfo(settings.clinic_timezone)
    now = datetime.now(UTC)
    found: dict[datetime, Doctor] = {}
    for doctor_id, name in doctors:
        availability = await appointment_service.get_availability(
            db, actor, doctor_id, day, settings.default_appointment_duration_minutes
        )
        for slot in availability.slots:
            if not slot.available or slot.start <= now:
                continue
            hour = slot.start.astimezone(tz).hour
            if (part_of_day == "morning" and hour >= 12) or (
                part_of_day == "afternoon" and hour < 12
            ):
                continue
            found.setdefault(slot.start, (doctor_id, name))
    return [(start, *found[start]) for start in sorted(found)]


async def offer_times(
    db: AsyncSession,
    actor: User,
    pool: tuple[list[Doctor], list[Doctor]],
    day: date,
    *,
    part_of_day: str | None = None,
) -> list[tuple[date, list[Slot]]]:
    """The requested day if it has anything free (first-choice doctors, then
    the fallback), otherwise the nearest days that do, closest first, never in
    the past. Empty means nothing within NEAREST_SPAN_DAYS either side."""
    first, fallback = pool
    slots = await free_on_day(db, actor, first, day, part_of_day=part_of_day)
    if not slots and fallback:
        slots = await free_on_day(db, actor, fallback, day, part_of_day=part_of_day)
    if slots:
        return [(day, slots[:MAX_SLOTS_PER_DAY])]
    everyone = first + [d for d in fallback if d not in first]
    today = appointment_service.clinic_date(datetime.now(UTC))
    nearest: list[tuple[date, list[Slot]]] = []
    for offset in range(1, NEAREST_SPAN_DAYS + 1):
        for candidate in (day + timedelta(days=offset), day - timedelta(days=offset)):
            if candidate < today:
                continue
            found = await free_on_day(db, actor, everyone, candidate, part_of_day=part_of_day)
            if found:
                nearest.append((candidate, found[: MAX_SLOTS_PER_DAY // NEAREST_DAYS_OFFERED]))
            if len(nearest) == NEAREST_DAYS_OFFERED:
                return nearest
    return nearest
