"""Give every registered patient without an active doctor one.

New patients get a doctor when staff create or promote them
(assignment_service.ensure_doctor). This is the one-off catch-up for the
patients registered before that: the same rule, their preferred doctor while
active, else the least-loaded active doctor. A corpus patient with no
preference on record first gets the "Assigned doctor" on their own registration
form as that preference, so the doctor the system gives them is the one their
documents and visit history name. Provisional and purged patients are skipped.
Audited as patient.doctor_assigned by the agent account.

Dry run by default: prints what it would do and changes nothing.

Usage (against a database migrated to head):
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \\
        python -m scripts.assign_missing_doctors            # dry run
    ... python -m scripts.assign_missing_doctors --apply    # for real
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient
from app.models.user import User, UserRole
from app.services import assignment_service
from app.services.booking_service import doctor_for_patient
from app.services.doctor_suggestion import suggest_doctor_for_patient
from scripts.seed_demo_patients import _CORPUS_DIR, _UUID_RE, _field


def documented_doctors() -> dict[UUID, str]:
    """Patient id -> the "Assigned doctor" named on that patient's corpus
    registration form. Empty where there is no corpus."""
    named: dict[UUID, str] = {}
    if not _CORPUS_DIR.is_dir():
        return named
    for folder in _CORPUS_DIR.iterdir():
        form = folder / "Admin_Docs" / "registration_form.txt"
        match = _UUID_RE.search(folder.name)
        if match is None or not form.is_file():
            continue
        try:
            named[UUID(match.group(0))] = _field(
                form.read_text(encoding="utf-8"), "Assigned doctor"
            )
        except ValueError:
            continue  # a form with no doctor on it: the usual rule applies
    return named


async def _planned_doctor(
    db: AsyncSession, patient: Patient, documented: UUID | None = None
) -> UUID | None:
    preferred_id = patient.preferred_doctor_id or documented
    preferred = await db.get(User, preferred_id) if preferred_id else None
    if preferred is not None and preferred.role == UserRole.DOCTOR and preferred.is_active:
        return preferred.id
    return await suggest_doctor_for_patient(db, patient.id)


async def run(db: AsyncSession, *, actor: User, apply: bool) -> list[tuple[UUID, UUID | None]]:
    """(patient id, doctor id) for every doctorless registered patient: the
    doctor planned (dry run) or assigned (apply). A second apply finds none."""
    patients = (
        await db.scalars(
            select(Patient)
            .where(Patient.is_provisional.is_(False), Patient.purged_at.is_(None))
            .order_by(Patient.created_at, Patient.id)
        )
    ).all()
    named = documented_doctors()
    doctor_ids = {
        name: doctor_id
        for doctor_id, name in (
            await db.execute(
                select(User.id, User.full_name).where(
                    User.role == UserRole.DOCTOR, User.is_active.is_(True)
                )
            )
        ).tuples()
    }
    out: list[tuple[UUID, UUID | None]] = []
    for patient in patients:
        if await doctor_for_patient(db, patient.id) is not None:
            continue
        documented = doctor_ids.get(named.get(patient.id, ""))
        if apply:
            if patient.preferred_doctor_id is None and documented is not None:
                patient.preferred_doctor_id = documented
            out.append((patient.id, await assignment_service.ensure_doctor(db, patient, actor)))
        else:
            out.append((patient.id, await _planned_doctor(db, patient, documented)))
    if apply:
        await db.commit()
    return out


async def main() -> None:
    from app.database import AsyncSessionLocal
    from app.services.system_actor import get_or_create_agent_actor

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="assign for real")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        actor = await get_or_create_agent_actor(db)
        rows = await run(db, actor=actor, apply=args.apply)
    verb = "assigned" if args.apply else "would assign"
    for patient_id, doctor_id in rows:
        print(f"{verb} patient {patient_id} -> doctor {doctor_id or 'none (no active doctor)'}")
    print(f"{len(rows)} patient(s) without a doctor{'' if args.apply else ' (dry run)'}")


if __name__ == "__main__":
    asyncio.run(main())
