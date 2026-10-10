"""Turn each corpus patient's appointment_history.txt into appointment rows.

Without this the calendar and RAG disagree: RAG can answer "when did this
patient last visit" from the corpus text while the calendar shows nothing.
These are historical visits, so they are written past-dated and completed.

The corpus names doctors that may not exist as users. Rather than dropping
those visits, the matching doctor user is created once per name (this is a
synthetic-only dataset; see settings.synthetic_only). The synthetic email
domain uses .example (RFC 2606) rather than .local: pydantic's EmailStr
rejects .local as a reserved mDNS name, which broke GET /auth/users.

Idempotent: reference codes are derived from patient + date + doctor.

Usage:
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
        python -m scripts.ingest_appointment_history
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import hash_password
from app.config import settings
from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.services.appointment_service import clinic_date

_CORPUS_DIR = Path(__file__).resolve().parents[1] / "ingestion" / "matthew_corpus" / "Synth_Dataset"
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# "09/12/2024 - General Consultation - Dr Marcus O'Connell"
_VISIT_RE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*-\s*(.+?)\s*-\s*(Dr\s+.+?)\s*$")

_TYPE_MAP = {
    "general consultation": AppointmentType.FOLLOW_UP,
    "specialist referral": AppointmentType.PROCEDURE,
    "new patient registration": AppointmentType.NEW_PATIENT,
}


@dataclass(frozen=True)
class ParsedVisit:
    visit_date: date
    visit_type: str
    doctor_name: str


def parse_history(text: str) -> list[ParsedVisit]:
    """Extract visit lines. Malformed lines are skipped, never raised on:
    one bad line in one patient's file must not abort a 100-patient ingest.
    """
    visits: list[ParsedVisit] = []
    for line in text.splitlines():
        match = _VISIT_RE.match(line)
        if match is None:
            continue
        day, month, year, visit_type, doctor_name = match.groups()
        try:
            # Corpus dates are day-first.
            parsed = date(int(year), int(month), int(day))
        except ValueError:
            continue
        visits.append(
            ParsedVisit(
                visit_date=parsed, visit_type=visit_type.strip(), doctor_name=doctor_name.strip()
            )
        )
    return visits


def _reference_code(patient_id: uuid.UUID, visit: ParsedVisit) -> str:
    seed = f"{patient_id}{visit.visit_date}{visit.doctor_name}"
    return f"APT-{hashlib.sha256(seed.encode()).hexdigest()[:6].upper()}"


# The roster patients are quoted from. Reading it here keeps one list of the
# clinic's doctors: a doctor added to that table gets an account on the next
# seed, with no second list to update.
_ROSTER_FILE = (
    Path(__file__).resolve().parents[2] / "Organization Profile Review" / "01_Clinic_Identity.md"
)
_ROSTER_ROW = re.compile(r"^\|\s*(Dr [^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)


def clinic_roster() -> dict[str, str]:
    """Doctor name -> special interest, from the Practitioners table."""
    if not _ROSTER_FILE.is_file():
        print(f"no roster at {_ROSTER_FILE}: doctors come from the corpus only")
        return {}
    section = _ROSTER_FILE.read_text(encoding="utf-8").partition("## Practitioners")[2]
    return dict(_ROSTER_ROW.findall(section.partition("\n## ")[0]))


async def apply_roster(session: AsyncSession) -> None:
    """Every doctor on the roster has an account and their special interest.

    Some roster doctors have no visits in the corpus, so nothing else would
    create them and a patient asking for one by name would be told the clinic
    has no such doctor. The interest goes in User.department, which is what
    the registration form shows and what a request for a kind of doctor is
    matched against. One an admin has already set is left alone.
    """
    for name, interest in clinic_roster().items():
        doctor = await session.get(User, await doctor_user_id(session, name))
        assert doctor is not None  # doctor_user_id found or flushed it
        if not doctor.department:
            doctor.department = interest


def visit_slot(visit_date: date, earlier_that_day: int) -> datetime:
    """When a corpus visit is filed: 09:00 at the clinic on the visit's own
    date, half an hour later for each visit that doctor already has that day.
    The corpus gives a date and no time. Returned as a UTC instant."""
    start = datetime.combine(visit_date, time(hour=9), tzinfo=ZoneInfo(settings.clinic_timezone))
    return (start + timedelta(minutes=30 * earlier_that_day)).astimezone(UTC)


async def doctor_user_id(session: AsyncSession, name: str) -> uuid.UUID:
    """The doctor account for this name, created on first sight."""
    email = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".") + "@corpus.vitalai.example"
    found = (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if found is not None:
        return found
    doctor = User(
        email=email,
        hashed_password=hash_password(uuid.uuid4().hex),
        full_name=name,
        role=UserRole.DOCTOR,
    )
    session.add(doctor)
    await session.flush()
    return doctor.id


async def ingest() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is required")
    if not _CORPUS_DIR.exists():
        sys.exit(f"Corpus not found at {_CORPUS_DIR}")

    engine = create_async_engine(database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    today = clinic_date(datetime.now(UTC))

    async with sessionmaker() as session:
        doctor_cache: dict[str, uuid.UUID] = {}
        # Two different corpus patients can share a doctor on the same date;
        # the corpus has no visit time, so every visit defaults to 09:00 and
        # would otherwise collide with excl_doctor_overlap. Staggered by 30
        # minutes per prior visit for that (doctor, day), deterministically
        # by processing order, so re-running lands on the same slots.
        doctor_day_offsets: dict[tuple[uuid.UUID, date], int] = {}
        created = skipped = 0

        for folder in sorted(_CORPUS_DIR.iterdir()):
            history_file = folder / "Admin_Docs" / "appointment_history.txt"
            if not history_file.is_file():
                continue
            match = _UUID_RE.search(folder.name)
            if match is None:
                continue
            patient_id = uuid.UUID(match.group(0))

            patient = await session.get(Patient, patient_id)
            if patient is None:
                continue

            case_id = (
                await session.execute(
                    select(IntakeCase.id).where(IntakeCase.patient_id == patient_id).limit(1)
                )
            ).scalar_one_or_none()
            if case_id is None:
                case = IntakeCase(
                    patient_id=patient_id,
                    contact_reason="Historical visit",
                    contact_channel="manual",
                )
                session.add(case)
                await session.flush()
                case_id = case.id

            for visit in parse_history(history_file.read_text(encoding="utf-8")):
                if visit.visit_date >= today:
                    # Future-dated corpus entries are not history; leave them
                    # out rather than inventing confirmed future bookings.
                    skipped += 1
                    continue

                if visit.doctor_name not in doctor_cache:
                    doctor_cache[visit.doctor_name] = await doctor_user_id(
                        session, visit.doctor_name
                    )
                doctor_id = doctor_cache[visit.doctor_name]

                # Incremented for every visit seen for this (doctor, day),
                # including ones about to be skipped as duplicates below, so
                # the offset a visit lands on is stable across re-runs.
                day_key = (doctor_id, visit.visit_date)
                offset = doctor_day_offsets.get(day_key, 0)
                doctor_day_offsets[day_key] = offset + 1

                code = _reference_code(patient_id, visit)
                already = (
                    await session.execute(
                        select(Appointment.id).where(Appointment.reference_code == code)
                    )
                ).scalar_one_or_none()
                if already is not None:
                    continue

                session.add(
                    Appointment(
                        doctor_id=doctor_id,
                        case_id=case_id,
                        time_slot=visit_slot(visit.visit_date, offset),
                        duration_minutes=30,
                        appointment_type=_TYPE_MAP.get(
                            visit.visit_type.lower(), AppointmentType.OTHER
                        ),
                        status=AppointmentStatus.COMPLETED,
                        reason=visit.visit_type,
                        reference_code=code,
                    )
                )
                created += 1

        await apply_roster(session)

        await session.commit()
        print(f"inserted {created} historical appointments, skipped {skipped} future-dated")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(ingest())
