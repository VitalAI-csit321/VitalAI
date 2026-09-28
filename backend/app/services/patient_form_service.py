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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.task import TaskCategory

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
