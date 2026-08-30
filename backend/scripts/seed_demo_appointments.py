"""Seed a month of demo appointments over the existing demo patients.

The calendar is unusable for a demo when the month grid is empty. This fills
the current month with a deterministic, realistic spread: weekdays only,
inside clinic hours, no doctor double-booked (the 0026 exclusion constraint
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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.user import User, UserRole

_OPEN_HOUR = 8
_CLOSE_HOUR = 18
_SLOT_MINUTES = 30
_TYPES = ["new_patient", "follow_up", "procedure", "other"]
# Weighted so most appointments look normal: 60% confirmed, 20% completed,
# 13% cancelled, 7% pending. Deterministic, not random.
_STATUS_CYCLE = ["confirmed"] * 9 + ["completed"] * 3 + ["cancelled"] * 2 + ["pending"] * 1


def _stable_index(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16)


def build_demo_appointments(
    patient_ids: list[uuid.UUID],
    doctor_ids: list[uuid.UUID],
    month_start: datetime,
) -> list[dict]:
    """Plan one month of appointments. Pure: no DB, no randomness, no clock.

    Walks weekday slots in order and assigns patients round-robin, so the same
    inputs always produce the same plan and no (doctor, time_slot) repeats.
    """
    if not patient_ids or not doctor_ids:
        return []

    slots: list[tuple[uuid.UUID, datetime]] = []
    day = month_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day.month == month_start.month:
        if day.weekday() < 5:
            for doctor_id in doctor_ids:
                cursor = day.replace(hour=_OPEN_HOUR)
                closing = day.replace(hour=_CLOSE_HOUR)
                while cursor < closing:
                    slots.append((doctor_id, cursor))
                    cursor += timedelta(minutes=_SLOT_MINUTES)
        day += timedelta(days=1)

    # Book roughly a third of available slots so the calendar looks busy but
    # not saturated, and free slots remain for manual booking during a demo.
    plan: list[dict] = []
    for index, (doctor_id, slot) in enumerate(slots):
        if index % 3 != 0:
            continue
        patient_id = patient_ids[_stable_index(doctor_id, slot) % len(patient_ids)]
        plan.append(
            {
                "doctor_id": doctor_id,
                "patient_id": patient_id,
                "time_slot": slot,
                "duration_minutes": _SLOT_MINUTES,
                "appointment_type": _TYPES[_stable_index(slot, patient_id) % len(_TYPES)],
                "status": _STATUS_CYCLE[_stable_index(slot, doctor_id) % len(_STATUS_CYCLE)],
                "reference_code": (
                    f"APT-{hashlib.sha256(f'{doctor_id}{slot}'.encode()).hexdigest()[:6].upper()}"
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
        patient_ids = list((await session.execute(select(Patient.id).limit(120))).scalars().all())
        doctor_ids = list(
            (await session.execute(select(User.id).where(User.role == UserRole.DOCTOR)))
            .scalars()
            .all()
        )
        if not patient_ids:
            sys.exit("No patients found. Run scripts.seed_demo_patients first.")
        if not doctor_ids:
            sys.exit("No doctors found. Create at least one doctor user first.")

        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        plan = build_demo_appointments(patient_ids, doctor_ids, month_start)

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
