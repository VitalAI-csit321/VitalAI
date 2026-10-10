"""Seed a month of demo appointments over the existing demo patients.

The calendar is unusable for a demo when the month grid is empty. This fills
the current month with a deterministic, realistic spread: each patient with
their own doctor, clinic days only, inside clinic hours in the clinic's
timezone, no doctor double-booked (the 0026 exclusion constraint
would reject that anyway).

Idempotent: every generated row carries a reference_code derived from its
own content, so re-running upserts rather than duplicating.

Usage (against the docker-compose db, migrated to head):
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
        python -m scripts.seed_demo_appointments
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.assignment import DoctorPatientAssignment
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.services.appointment_service import clinic_date, is_clinic_day

_SLOT_MINUTES = 30
# A doctor's month is at most a third full, so free times remain for booking
# during a demo, and no patient is in more often than about once a week.
_VISITS_PER_PATIENT = 4
_TYPES = ["new_patient", "follow_up", "procedure", "other"]
# Weighted so most appointments look normal: 60% confirmed, 20% completed,
# 13% cancelled, 7% pending. Deterministic, not random.
_STATUS_CYCLE = ["confirmed"] * 9 + ["completed"] * 3 + ["cancelled"] * 2 + ["pending"] * 1


def _stable_index(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16)


def build_demo_appointments(
    patients_by_doctor: dict[uuid.UUID, list[uuid.UUID]],
    month_start: date,
) -> list[dict]:
    """Plan one month of appointments. Pure: no DB, no randomness, no clock.

    Each doctor sees only their own patients, in turn, in slots spread evenly
    over the month, so the same inputs always produce the same plan and no
    (doctor, time_slot) repeats. A doctor with no patients gets no appointments.

    Days and hours come from the rules bookings are held to (is_clinic_day and
    the clinic hours in the clinic's timezone), so a seeded appointment is one
    the app would have accepted. Slots are returned as UTC instants.
    """
    tz = ZoneInfo(settings.clinic_timezone)
    slots: list[datetime] = []
    day = date(month_start.year, month_start.month, 1)
    while day.month == month_start.month:
        if is_clinic_day(day):
            cursor = datetime.combine(day, time(hour=settings.clinic_open_hour), tzinfo=tz)
            closing = datetime.combine(day, time(hour=settings.clinic_close_hour), tzinfo=tz)
            while cursor < closing:
                slots.append(cursor.astimezone(UTC))
                cursor += timedelta(minutes=_SLOT_MINUTES)
        day += timedelta(days=1)

    plan: list[dict] = []
    for doctor_id in sorted(patients_by_doctor):
        patients = sorted(patients_by_doctor[doctor_id])
        wanted = min(len(slots) // 3, _VISITS_PER_PATIENT * len(patients))
        for n in range(wanted):
            slot = slots[n * len(slots) // wanted]
            patient_id = patients[n % len(patients)]
            plan.append(
                {
                    "doctor_id": doctor_id,
                    "patient_id": patient_id,
                    "time_slot": slot,
                    "duration_minutes": _SLOT_MINUTES,
                    "appointment_type": _TYPES[_stable_index(slot, patient_id) % len(_TYPES)],
                    "status": _STATUS_CYCLE[_stable_index(slot, doctor_id) % len(_STATUS_CYCLE)],
                    "reference_code": (
                        "APT-"
                        + hashlib.sha256(f"{doctor_id}{slot}".encode()).hexdigest()[:6].upper()
                    ),
                }
            )
    return plan


async def seed() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is required")

    engine = create_async_engine(database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with sessionmaker() as session:
        patients_by_doctor: dict[uuid.UUID, list[uuid.UUID]] = {}
        for doctor_id, patient_id in (
            await session.execute(
                select(DoctorPatientAssignment.doctor_id, DoctorPatientAssignment.patient_id)
                .join(User, User.id == DoctorPatientAssignment.doctor_id)
                .join(Patient, Patient.id == DoctorPatientAssignment.patient_id)
                .where(User.role == UserRole.DOCTOR, User.is_active.is_(True))
            )
        ).tuples():
            patients_by_doctor.setdefault(doctor_id, []).append(patient_id)
        if not patients_by_doctor:
            sys.exit(
                "No patient has a doctor. Run scripts.seed_demo_patients, "
                "scripts.ingest_appointment_history and "
                "scripts.assign_missing_doctors --apply first."
            )

        # The month it is at the clinic, which near a month's end is not
        # always the month it is in UTC.
        month_start = clinic_date(datetime.now(UTC)).replace(day=1)
        plan = build_demo_appointments(patients_by_doctor, month_start)

        # One case per patient, reused across that patient's appointments.
        cases: dict[uuid.UUID, uuid.UUID] = {}
        for patient_id in {row["patient_id"] for row in plan}:
            existing = (
                await session.execute(
                    select(IntakeCase.id).where(IntakeCase.patient_id == patient_id).limit(1)
                )
            ).scalar_one_or_none()
            if existing is None:
                case = IntakeCase(
                    patient_id=patient_id,
                    contact_reason="Demo appointment",
                    contact_channel="manual",
                )
                session.add(case)
                await session.flush()
                existing = case.id
            cases[patient_id] = existing

        created = 0
        for row in plan:
            already = (
                await session.execute(
                    select(Appointment.id).where(
                        Appointment.reference_code == row["reference_code"]
                    )
                )
            ).scalar_one_or_none()
            if already is not None:
                continue
            session.add(
                Appointment(
                    doctor_id=row["doctor_id"],
                    case_id=cases[row["patient_id"]],
                    time_slot=row["time_slot"],
                    duration_minutes=row["duration_minutes"],
                    appointment_type=AppointmentType(row["appointment_type"]),
                    status=AppointmentStatus(row["status"]),
                    reference_code=row["reference_code"],
                )
            )
            created += 1

        await session.commit()
        print(f"planned {len(plan)} appointments, inserted {created} new")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
