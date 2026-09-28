"""The registration form link (spec 2026-09-28-patient-registration-form-link).

An unknown sender who asks to book or to sign up gets a link to a web form
instead of an email asking them to type their details. What they type is
stored as typed: no model reads it. After the form, the existing email
conversation (email_conversation_service) takes over from the offered times.

The token's hash is how a link finds its conversation. The token itself is
also in the sent email, the Task's draft_text and the graph checkpoint,
because it is part of the email body: the hash is a lookup, not a promise
that the token is nowhere at rest. A token can submit one registration for
the address it was sent to, and read nothing.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.llm.output_guardrail import OutputBlockedError, check_output
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.patient import Patient
from app.models.task import Task, TaskCategory, TaskSource
from app.models.user import User
from app.schemas.registration import RegistrationSubmit
from app.services import (
    booking_service,
    consent_service,
    email_conversation_service,
    email_service,
    identity_service,
    patient_service,
)
from app.services.audit_service import record_event
from app.services.draft_critic import critique
from app.services.identity_service import IdentityFields, IdentityOutcome
from app.services.system_actor import get_or_create_agent_actor

logger = logging.getLogger(__name__)

FORM_LINK_DAYS = 7
# A urlsafe token of 32 bytes is 43 characters; anything far longer is not one.
_MAX_TOKEN_LENGTH = 100

WAITING_REASON = "Registration link sent. Waiting for the patient to complete the form."

_SIGN_OFF = "\n\nKind regards,\nThe clinic team"


def enabled() -> bool:
    return (
        settings.patient_form_link_enabled
        and settings.agentic_pipeline_enabled
        and settings.email_booking_conversation_enabled
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_link(conversation: EmailConversation) -> str:
    """A new link for this conversation. The caller commits; the link only
    opens once record_sent has stamped form_sent_at."""
    token = secrets.token_urlsafe(32)
    conversation.form_token_hash = token_hash(token)
    # ponytail: the first CORS origin is the frontend, as for the password
    # reset link; add a dedicated setting when that stops being true.
    return f"{settings.cors_origins_list[0]}/register/{token}"


def needs_preferred_day(conversation: EmailConversation) -> bool:
    return conversation.original_intent == TaskCategory.APPOINTMENT_REQUEST.value


async def find_open(
    db: AsyncSession, token: str, *, lock: bool = False
) -> EmailConversation | None:
    """The conversation this link belongs to, if the link can still be used.
    lock=True takes a row lock, so two submits cannot both get through."""
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    query = select(EmailConversation).where(EmailConversation.form_token_hash == token_hash(token))
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if (
        row is None
        or row.origin_email_id is None
        or row.form_sent_at is None
        or row.form_submitted_at is not None
        or row.stage != ConversationStage.AWAITING_DETAILS
    ):
        return None
    sent = row.form_sent_at if row.form_sent_at.tzinfo else row.form_sent_at.replace(tzinfo=UTC)
    if datetime.now(UTC) - sent >= timedelta(days=FORM_LINK_DAYS):
        return None
    return row


def link_text(link: str) -> str:
    return (
        "Hello,\n\n"
        "Thank you for contacting the clinic. To register with us, please fill in "
        "this short form:\n\n"
        f"{link}\n\n"
        "It asks for your name, date of birth, phone number, the day you would prefer "
        "to come in, and your consent. There is no need to send those details by email.\n\n"
        f"The link can be used once and expires in {FORM_LINK_DAYS} days. When the form "
        "is done we will email you your reference number and the times available." + _SIGN_OFF
    )


CONSENT_TYPE = "online_registration"
CONSENT_STATEMENTS = (
    "I agree to the clinic collecting and keeping my details to register me and arrange "
    "appointments.",
    "I agree to be contacted by email and phone about my appointments.",
)
_CONSENT_NOTES = "Given on the online registration form. Check photo ID, then verify it."
# The optional fields the form offers, stored as typed.
EXTRAS = (
    "gender",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "preferred_language",
    "preferred_communication",
)
SUBMITTED_REASON = "The patient completed the registration form."


class RegistrationRejectedError(Exception):
    """The form cannot be accepted as sent. The message is shown to the patient."""


async def task_for(db: AsyncSession, case_id: UUID) -> Task | None:
    """The Task of the email that opened the case. Task has no email column,
    and later emails on the case add Tasks of their own."""
    return (
        await db.execute(
            select(Task)
            .where(Task.case_id == case_id, Task.source == TaskSource.EMAIL)
            .order_by(Task.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


def _check_day(conversation: EmailConversation, day) -> None:
    if day is None:
        if needs_preferred_day(conversation):
            raise RegistrationRejectedError("Please choose the day you would prefer to come in.")
        return
    today = datetime.now(ZoneInfo(settings.clinic_timezone)).date()
    window = email_conversation_service.BOOKING_WINDOW_DAYS
    if not today <= day <= today + timedelta(days=window):
        raise RegistrationRejectedError(
            f"Please choose a day between today and {window // 7} weeks from now."
        )


def _given(payload: RegistrationSubmit) -> list[str]:
    """Which fields were filled in, for the audit log. Never their values."""
    skip = {"signature", "agree_data", "agree_contact"}
    return sorted(k for k, v in payload.model_dump(exclude=skip).items() if v)


async def _audit(db, actor, conversation, outcome: str, patient_id, given) -> None:
    await record_event(
        db,
        actor=actor,
        case_id=conversation.case_id,
        action="patient.form_submitted",
        details={
            "conversation_id": str(conversation.id),
            "patient_id": str(patient_id) if patient_id else None,
            "outcome": outcome,
            "fields": given,
        },
    )


async def submit(
    db: AsyncSession, conversation: EmailConversation, payload: RegistrationSubmit, actor: User
) -> Patient | None:
    """Record a submitted form. Returns the patient it landed on, or None
    when the details partly match someone else and staff take over.

    One transaction on the row find_open(lock=True) locked. Nothing commits
    until create_consent_record, which is written last and commits it all.
    """
    _check_day(conversation, payload.preferred_day)
    now = datetime.now(UTC)
    conversation.form_submitted_at = now
    origin = await db.get(Email, conversation.origin_email_id)
    address = origin.sender.strip()
    task = await task_for(db, conversation.case_id)
    given = _given(payload)
    extras = {field: getattr(payload, field) for field in EXTRAS}

    # A record already exists when the patient answered by email before
    # using the link; the form fills it rather than making a second one.
    patient = await db.get(Patient, conversation.patient_id) if conversation.patient_id else None
    outcome = "existing"
    if patient is None:
        result = await identity_service.resolve_patient(
            db,
            sender=address,
            fields=IdentityFields(name=payload.name, dob=payload.dob, phone=payload.phone),
        )
        if result.outcome == IdentityOutcome.AMBIGUOUS:
            conversation.stage = ConversationStage.STAFF.value
            if task is not None:
                # Staff act on these, so the Task carries them; the audit log does not.
                task.handover_context = (
                    f"{email_conversation_service.STAFF_REASONS['ambiguous']} The registration "
                    f"form gave: {payload.name}, born {payload.dob:%d/%m/%Y}, "
                    f"phone {payload.phone}."
                )
            await _audit(db, actor, conversation, "ambiguous", None, given)
            await db.commit()
            return None
        patient, outcome = result.patient, "matched"

    if patient is None:
        patient = await patient_service.create_provisional_patient(
            db,
            case_id=conversation.case_id,
            name=payload.name,
            email=address,
            phone=payload.phone,
            dob=payload.dob,
            actor=actor,
            commit=False,
        )
        for field, value in extras.items():
            setattr(patient, field, value)
        outcome = "created"
    elif patient.is_provisional:
        # Fills gaps only; a value already on file is never overwritten.
        await patient_service.fill_provisional_fields(
            db,
            patient,
            actor=actor,
            name=payload.name,
            dob=payload.dob,
            phone=payload.phone,
            email=address,
            **extras,
        )

    conversation.patient_id = patient.id
    case = await db.get(IntakeCase, conversation.case_id)
    if case is not None and case.patient_id is None:
        case.patient_id, case.patient_name = patient.id, patient.name
    conversation.preferred_day = payload.preferred_day
    if task is not None:
        task.handover_context = SUBMITTED_REASON
    await _audit(db, actor, conversation, outcome, patient.id, given)
    await consent_service.create_consent_record(
        db,
        conversation.case_id,
        actor,
        consent_type=CONSENT_TYPE,
        notes=_CONSENT_NOTES,
        form_snapshot={
            "checks": [{"label": s, "checked": True} for s in CONSENT_STATEMENTS],
            "signature": payload.signature,
            "submitted_at": now.isoformat(),
        },
    )
    return patient


OFFERED_REASON = "The patient completed the registration form and was offered times by email."
FOLLOWUP_FAILED_REASON = (
    "The patient completed the registration form, but the email with their MRN and "
    "times could not be sent. Contact them by hand."
)


async def send_followup(conversation_id: UUID, part_of_day: str | None) -> None:
    """After a submitted form: the MRN and the free times, as a reply in the
    original thread so the patient's answer links back to the case.

    Runs after the response, in a session of its own. Anything that goes
    wrong leaves the registration in place and says so on the Task.
    """
    async with AsyncSessionLocal() as db:
        try:
            await _followup(db, conversation_id, part_of_day)
        except Exception as exc:
            # The type only: this was raised while writing to a patient.
            logger.error(
                "Registration follow-up for conversation %s failed (%s)",
                conversation_id,
                type(exc).__name__,
            )
            await db.rollback()
            conversation = await db.get(EmailConversation, conversation_id)
            task = await task_for(db, conversation.case_id) if conversation else None
            if task is not None:
                task.handover_context = FOLLOWUP_FAILED_REASON
                await db.commit()


async def _followup(db: AsyncSession, conversation_id: UUID, part_of_day: str | None) -> None:
    actor = await get_or_create_agent_actor(db)
    conversation = await db.get(EmailConversation, conversation_id)
    patient = await db.get(Patient, conversation.patient_id)
    origin = await db.get(Email, conversation.origin_email_id)
    task = await task_for(db, conversation.case_id)

    days: list = []
    if conversation.preferred_day is not None:
        pool = await booking_service.doctor_pool(db, patient.id)
        days = await booking_service.offer_times(
            db, actor, pool, conversation.preferred_day, part_of_day=part_of_day
        )
    # The MRN only to the address on the record, the rule the email flow uses.
    own = (patient.email or "").strip().casefold() == origin.sender.strip().casefold()
    text = email_conversation_service.registered_text(
        name=patient.name,
        mrn=patient.mrn if own else None,
        requested=conversation.preferred_day,
        days=days,
    )
    blocked = critique(text, branch=email_conversation_service.BRANCH) is not None
    if not blocked:
        try:
            await check_output(db, text, actor=actor, case_id=conversation.case_id)
        except OutputBlockedError:
            blocked = True
    if blocked:
        if task is not None:
            task.handover_context = FOLLOWUP_FAILED_REASON
            await db.commit()
        return

    # task_id=None: the Task's draft_sent is already true from the link email,
    # and deliver_reply would take that to mean this one went out too.
    # form_submitted_at is what stops a second follow-up.
    await email_service.deliver_reply(
        db,
        email_id=origin.id,
        task_id=None,
        draft=text,
        actor=actor,
        case_id=conversation.case_id,
        automated=True,
    )
    if days:
        stage, note = ConversationStage.AWAITING_CHOICE, OFFERED_REASON
    elif conversation.preferred_day is None:
        stage, note = ConversationStage.AWAITING_DETAILS, SUBMITTED_REASON
    else:
        stage, note = ConversationStage.STAFF, email_conversation_service.STAFF_REASONS["no_slots"]
    if task is not None:
        task.handover_context = note
    await email_conversation_service.record_sent(
        db,
        conversation.id,
        text=text,
        next_stage=stage.value,
        offer=email_conversation_service.offer_payload(days),
        verification=False,
    )
