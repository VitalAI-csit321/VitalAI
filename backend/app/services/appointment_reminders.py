"""Remind a patient the day before their appointment (build spec §16).

A reminder is a scheduled outbound message, not a reply to an inbound one.
It is not part of the agent graph and not an agent: no model, no critic, no
approval. A fixed template with no clinical content in it is low-risk
auto-send in the sense §4 defines, so it goes out without a human clicking,
through the same delivery module as every other outbound message.

Ownership of the idempotency guard lives here and nowhere else: this module
sets reminder_sent_at, and only after deliver_new_message has returned
without raising. email_service knows nothing about appointments, and clearing
the column again belongs to whatever moves time_slot.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.user import User
from app.services import email_service
from app.services.audit_service import record_event
from app.services.booking_service import format_slot
from app.services.outlook_auth import OutlookAuthRequiredError
from app.services.system_actor import get_or_create_agent_actor

logger = logging.getLogger(__name__)

SUBJECT = "A reminder about your appointment"
HORIZON = timedelta(hours=24)

SENT_ACTION = "appointment.reminder_sent"
# One aggregate event per cycle, never one per appointment: at a 15 minute
# interval a single permanently bad row would otherwise write 96 audit rows a
# day, for as long as the appointment is in the window.
SKIPPED_ACTION = "appointment.reminders_skipped"


def render_reminder(appointment: Appointment, *, name: str | None) -> str:
    """When, where, the reference, and how to change it. Nothing else.

    `reason` and `internal_notes` are deliberately not read here at all: both
    are staff-facing free text that can carry clinical detail, and an email
    can be read by anyone with access to that inbox (§16.5).

    The time is the clinic's local time, via format_slot, which is the same
    helper the booking proposals use. A reminder saying "03:00" to a patient
    in Sydney is worse than no reminder.
    """
    where = f" at {appointment.location}" if appointment.location else ""
    return (
        f"Hi {name.split()[0] if name else 'there'},\n\n"
        f"This is a reminder that you have an appointment on "
        f"{format_slot(appointment.time_slot)}{where}.\n\n"
        f"Your reference is {appointment.reference_code}.\n\n"
        "If you need to change the time or cannot make it, please reply to this email "
        "or call the clinic and quote that reference.\n\n"
        "Kind regards,\nThe clinic team"
    )


def _skip_reason(patient: Patient | None) -> str | None:
    """Why this appointment gets no reminder, or None to send it.

    The recipient is the patient's recorded address and never the inbound
    Email.sender: that address came from an unverified message, and a
    reminder goes only to a contact the clinic actually holds (§16.4).

    Provisional patients cannot be booked at all (§9), so that guard should
    never fire, which is exactly why it is worth having.
    """
    if patient is None:
        return "case has no patient"
    if patient.is_provisional:
        return "patient is provisional"
    if patient.purged_at is not None:
        return "patient record has been purged"
    if not patient.email:
        return "patient has no email address"
    return None


async def send_due_reminders(db: AsyncSession, actor: User) -> list[UUID]:
    """One sweep cycle. Returns the ids of the appointments it reminded.

    The lower bound on the window means an appointment that has already
    started is never reminded, which also bounds retries for free: a
    permanently bad address stops producing events once its appointment
    begins.
    """
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Appointment, Patient)
            .join(IntakeCase, IntakeCase.id == Appointment.case_id)
            # Outer, so a case with no patient is a row to skip and audit
            # rather than a row that silently vanishes from the sweep.
            .outerjoin(Patient, Patient.id == IntakeCase.patient_id)
            .where(
                # PENDING rows (what suggest_slots writes) are excluded by
                # this, as are CANCELLED and COMPLETED.
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.notify_patient.is_(True),
                Appointment.reminder_sent_at.is_(None),
                Appointment.time_slot > now,
                Appointment.time_slot <= now + HORIZON,
            )
        )
    ).all()

    reminded: list[UUID] = []
    skipped: list[str] = []
    for appointment, patient in rows:
        reason = _skip_reason(patient)
        if reason is not None:
            logger.info("No reminder for appointment %s: %s", appointment.id, reason)
            skipped.append(str(appointment.id))
            continue
        try:
            await email_service.deliver_new_message(
                db,
                to_address=patient.email,
                subject=SUBJECT,
                body=render_reminder(appointment, name=patient.name),
                actor=actor,
                case_id=appointment.case_id,
                action=SENT_ACTION,
                details={
                    "appointment_id": str(appointment.id),
                    "case_id": str(appointment.case_id),
                },
            )
        except OutlookAuthRequiredError:
            # Nobody is signed in to the mailbox. That is one problem for the
            # whole cycle, not one per appointment, so stop rather than fail
            # once per row. The next cycle retries.
            logger.warning("Appointment reminders stopped for this cycle: no signed-in mailbox")
            break
        except Exception as exc:
            # reminder_sent_at stays NULL, so the next cycle retries.
            #
            # The type, not the traceback: a failure here is raised while
            # sending to a patient's address, and logs are a lower trust
            # surface than the patient row. The appointment id is enough to
            # find the recipient for anyone entitled to look it up. Same
            # split task_service.record_agent_failure already makes.
            logger.error(
                "Reminder for appointment %s could not be sent (%s)",
                appointment.id,
                type(exc).__name__,
            )
            skipped.append(str(appointment.id))
            continue
        appointment.reminder_sent_at = datetime.now(UTC)
        await db.commit()
        reminded.append(appointment.id)

    if skipped:
        await record_event(
            db,
            actor=actor,
            # Not scoped to a case: this one event covers several
            # appointments, which may belong to different cases.
            case_id=None,
            action=SKIPPED_ACTION,
            details={"count": len(skipped), "appointment_ids": skipped},
        )
        await db.commit()
    return reminded


async def remind_once() -> None:
    async with AsyncSessionLocal() as db:
        # record_event requires a real actor row and a sweep has no logged-in
        # user, the same problem the purge sweep already answers this way.
        actor = await get_or_create_agent_actor(db)
        reminded = await send_due_reminders(db, actor)
        if reminded:
            logger.info("Sent %d appointment reminders", len(reminded))


async def run_reminders() -> None:
    """Sweep until cancelled. One bad cycle must not kill the loop: nothing
    restarts it short of an app restart (same policy as the purge sweep and
    the Outlook poller)."""
    logger.info(
        "Appointment reminder sweep started, interval=%ds, horizon=%dh",
        settings.appointment_reminder_interval_seconds,
        HORIZON // timedelta(hours=1),
    )
    while True:
        try:
            await remind_once()
        except asyncio.CancelledError:
            logger.info("Appointment reminder sweep stopping")
            raise
        except Exception:
            logger.exception("Appointment reminder cycle failed")
        await asyncio.sleep(settings.appointment_reminder_interval_seconds)
