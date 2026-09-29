"""Anonymise provisional patients nobody claimed (build spec §9.1).

Never a DELETE. No foreign key referencing patients.id declares an ondelete,
so a delete raises, and rows named in audit details must stay where the hash
chain expects them. The patient record is anonymised in place; the
originating Email and IntakeCase are kept, by Amin's decision, so the
accurate wording is "the provisional patient record is anonymised after 90
days", not "no personal data is retained". A purged patient's upcoming
appointments are cancelled, and the patient is emailed first, while the
address still exists.
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
from app.models.appointment import Appointment, AppointmentStatus
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.patient import PROFILE_FIELDS, Patient, PatientStatus
from app.models.user import User
from app.services import consent_service, email_service
from app.services.audit_service import record_event
from app.services.booking_service import format_slot
from app.services.system_actor import get_or_create_agent_actor

logger = logging.getLogger(__name__)

PURGED_NAME = "[purged]"
NOTICE_SUBJECT = "Your appointment has been cancelled"
_UPCOMING = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


def purge_cancellation_text(slots: list[datetime]) -> str:
    """Names nobody (the identity was never verified) and invents no phone
    number or link: the clinic's contact details are not a setting."""
    if len(slots) == 1:
        what = (
            f"Your appointment on {format_slot(slots[0])} has been cancelled because your "
            "registration with the clinic was not completed."
        )
    else:
        what = (
            "These appointments have been cancelled because your registration with the "
            "clinic was not completed:\n" + "\n".join(f"- {format_slot(s)}" for s in slots)
        )
    return (
        f"Hello,\n\n{what}\n\n"
        "You are welcome to book again at any time. Please contact the clinic to arrange a "
        "new appointment.\n\nKind regards,\nThe clinic team"
    )


async def _appointments(db: AsyncSession, patient_id: UUID) -> list[Appointment]:
    return list(
        (
            await db.execute(
                select(Appointment)
                .join(IntakeCase, IntakeCase.id == Appointment.case_id)
                .where(IntakeCase.patient_id == patient_id)
                .order_by(Appointment.time_slot)
            )
        ).scalars()
    )


def _aware(instant: datetime) -> datetime:
    return instant if instant.tzinfo else instant.replace(tzinfo=UTC)


async def _notify(db: AsyncSession, actor: User, patient: Patient, upcoming: list[Appointment]):
    """Before anything is blanked: the address goes with the purge. A failed
    send does not stop the purge; retention wins, and afterwards there is no
    address to retry with."""
    assert patient.email  # the purge only notifies patients with an address
    ids = [str(a.id) for a in upcoming]
    try:
        await email_service.deliver_new_message(
            db,
            to_address=patient.email,
            subject=NOTICE_SUBJECT,
            body=purge_cancellation_text([_aware(a.time_slot) for a in upcoming]),
            actor=actor,
            case_id=upcoming[0].case_id,
            action="appointment.purge_notice_sent",
            details={"patient_id": str(patient.id), "appointment_ids": ids},
        )
    except Exception as exc:
        await record_event(
            db,
            actor=actor,
            case_id=upcoming[0].case_id,
            action="appointment.purge_notice_failed",
            # The type only, never the address.
            details={
                "patient_id": str(patient.id),
                "appointment_ids": ids,
                "error": type(exc).__name__,
            },
        )


async def _cancel(db: AsyncSession, actor: User, appointments: list[Appointment], now) -> None:
    """Cancelled, not deleted: audit details name these ids. Cancelling frees
    the slot, since excl_doctor_overlap covers confirmed and completed only.
    Notes go on every appointment, past ones too: they can carry personal detail."""
    for appointment in appointments:
        if appointment.status in _UPCOMING and _aware(appointment.time_slot) > now:
            appointment.status = AppointmentStatus.CANCELLED
            await record_event(
                db,
                actor=actor,
                case_id=appointment.case_id,
                action="appointment.cancelled",
                details={
                    "appointment_id": str(appointment.id),
                    "cancel_reason": "patient record purged",
                    "notify_patient": True,
                },
            )
        appointment.reason = None
        appointment.internal_notes = None


async def _drop_online_signatures(db: AsyncSession, actor: User, patient_id: UUID) -> None:
    """The registration form's drawn signature is personal data like the rest
    of the record. The statements agreed to stay. A consent nobody verified is
    withdrawn: there is no longer anyone on the record to check ID against."""
    records = (
        await db.execute(
            select(ConsentRecord)
            .join(IntakeCase, IntakeCase.id == ConsentRecord.case_id)
            .where(
                IntakeCase.patient_id == patient_id,
                ConsentRecord.consent_type == consent_service.ONLINE_REGISTRATION,
            )
        )
    ).scalars()
    for record in records:
        record.form_snapshot = {**(record.form_snapshot or {}), "signature": None}
        if record.status == ConsentStatus.PENDING:
            record.status = ConsentStatus.WITHDRAWN
            await record_event(
                db,
                actor=actor,
                case_id=record.case_id,
                action="consent.withdrawn",
                details={"consent_id": str(record.id), "reason": "patient record purged"},
            )


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
        now = datetime.now(UTC)
        appointments = await _appointments(db, patient.id)
        upcoming = [a for a in appointments if a.status in _UPCOMING and _aware(a.time_slot) > now]
        if upcoming and patient.email:
            await _notify(db, actor, patient, upcoming)
        await _cancel(db, actor, appointments, now)
        await _drop_online_signatures(db, actor, patient.id)
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
        # One patient at a time: their notice has gone, so their cancellations
        # and anonymising must not roll back with a later patient's failure,
        # or tomorrow's run would email them again.
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
