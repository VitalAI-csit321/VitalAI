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
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.patient import Patient
from app.models.task import Task, TaskCategory, TaskSource
from app.models.user import User
from app.schemas.registration import RegistrationSubmit
from app.services import (
    consent_service,
    email_conversation_service,
    identity_service,
    patient_service,
)
from app.services.audit_service import record_event
from app.services.identity_service import IdentityFields, IdentityOutcome

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
