"""Give every registered patient without an active doctor one (M4 spec, E6).

New patients get a doctor when staff create or promote them
(assignment_service.ensure_doctor). This is the one-off catch-up for the
patients registered before that: the same rule, their preferred doctor while
active, else the least-loaded active doctor. Provisional and purged patients
are skipped. Audited as patient.doctor_assigned by the agent account.

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


async def _planned_doctor(db: AsyncSession, patient: Patient) -> UUID | None:
    preferred = (
        await db.get(User, patient.preferred_doctor_id) if patient.preferred_doctor_id else None
    )
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
    out: list[tuple[UUID, UUID | None]] = []
    for patient in patients:
        if await doctor_for_patient(db, patient.id) is not None:
            continue
        if apply:
            out.append((patient.id, await assignment_service.ensure_doctor(db, patient, actor)))
        else:
            out.append((patient.id, await _planned_doctor(db, patient)))
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
