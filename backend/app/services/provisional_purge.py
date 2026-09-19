"""Anonymise provisional patients nobody claimed (build spec §9.1).

Never a DELETE. No foreign key referencing patients.id declares an ondelete,
so a delete raises, and rows named in audit details must stay where the hash
chain expects them. The patient record is anonymised in place; the
originating Email and IntakeCase are kept, by Amin's decision, so the
accurate wording is "the provisional patient record is anonymised after 90
days", not "no personal data is retained".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.case import IntakeCase
from app.models.patient import PROFILE_FIELDS, Patient, PatientStatus
from app.models.user import User
from app.services.audit_service import record_event
from app.services.system_actor import get_or_create_agent_actor

logger = logging.getLogger(__name__)

PURGED_NAME = "[purged]"


async def purge_due(db: AsyncSession, actor: User) -> list[UUID]:
    """Anonymise every provisional patient past the TTL. Returns their ids.

    A promoted patient is no longer provisional, so it can never be selected,
    and purged_at makes a second run a no-op.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.provisional_patient_ttl_days)
    due = (
        (
            await db.execute(
                select(Patient).where(
                    Patient.is_provisional.is_(True),
                    Patient.purged_at.is_(None),
                    Patient.created_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    for patient in due:
        patient.name = PURGED_NAME  # still NOT NULL
        patient.dob = None
        patient.gender = None
        for field in PROFILE_FIELDS:
            setattr(patient, field, None)
        patient.status = PatientStatus.INACTIVE
        patient.purged_at = datetime.now(UTC)
        # A copy of the name lives on every case; scrubbing only the patient
        # row would leave it behind.
        await db.execute(
            update(IntakeCase).where(IntakeCase.patient_id == patient.id).values(patient_name=None)
        )
        await record_event(
            db,
            actor=actor,
            action="patient.purged",
            details={
                "patient_id": str(patient.id),
                "mrn": patient.mrn,
                "ttl_days": settings.provisional_patient_ttl_days,
            },
        )
    await db.commit()
    return [p.id for p in due]


async def purge_once() -> None:
    async with AsyncSessionLocal() as db:
        actor = await get_or_create_agent_actor(db)
        purged = await purge_due(db, actor)
        if purged:
            logger.info("Purged %d unclaimed provisional patients", len(purged))


async def run_purge() -> None:
    """Sweep until cancelled. One bad cycle must not kill the loop: nothing
    restarts it short of an app restart (same policy as the Outlook poller)."""
    logger.info(
        "Provisional purge sweep started, interval=%ds, ttl=%d days",
        settings.provisional_purge_interval_seconds,
        settings.provisional_patient_ttl_days,
    )
    while True:
        try:
            await purge_once()
        except asyncio.CancelledError:
            logger.info("Provisional purge sweep stopping")
            raise
        except Exception:
            logger.exception("Provisional purge cycle failed")
        await asyncio.sleep(settings.provisional_purge_interval_seconds)
