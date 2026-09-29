"""Multi-turn email on one case: verification requests and the booking flow.

Behind email_booking_conversation_enabled. The turns:

1. An appointment request. A provisional profile if the sender is new and
   gave a name, and an acknowledgement asking for whatever is still missing
   plus a preferred day, saying the booking cannot be made without them and
   giving the MRN.
2. A reply with details and a day. The profile is filled in and the free
   times that day are offered, or the nearest days that have any.
3. A reply picking a time. If it is one we offered, every required detail is
   on file and it is still free, it is booked and confirmed.

Anything unclear gets one clarifying reply, and the second time a human.
Every reply is a fixed template, never a generation: what time the clinic told
a patient to come in is not a model's call. The model's only job is reading
the patient's reply, into a typed schema, and code checks everything it says.

A patient-specific inquiry from someone who cannot be identified gets the
verification request (request_verification), and their reply comes back here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseLanguageModel
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.guardrail import InputBlockedError, guarded_invoke
from app.models.appointment import AppointmentType
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.email_conversation import OPEN_STAGES, ConversationStage, EmailConversation
from app.models.human_review import TaskType
from app.models.patient import Patient
from app.models.task import TaskCategory
from app.models.user import User
from app.services import (
    appointment_service,
    booking_service,
    identity_service,
    onboarding_service,
    patient_service,
    reply_parsing,
    review_routing,
)
from app.services.audit_service import record_event
from app.services.identity_service import IdentityFields, IdentityOutcome

BRANCH = "booking_conversation"
VERIFICATION_BRANCH = "verification"

# Below this the extraction is a guess, and a guess does not get acted on.
MIN_CONFIDENCE = 0.6
# How far ahead a patient may ask for.
BOOKING_WINDOW_DAYS = 60
# The sender-address fallback for linking a reply that lost its headers.
LINK_FALLBACK_DAYS = 14

_MESSAGE_ID = re.compile(r"<[^<>\s]+>")
_MRN = re.compile(r"\bMRN-[A-Z0-9]{4,}\b", re.IGNORECASE)
_NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)@", re.IGNORECASE)

FIELD_LABELS = {
    "name": "your full name",
    "dob": "your date of birth",
    "phone": "a phone number we can reach you on",
}

# Why a conversation went to a human, as the Task says it.
STAFF_REASONS = {
    "cancel": "The patient asked to cancel during an email booking conversation. "
    "Nothing was sent; reply by hand.",
    "question": "The patient asked a question during an email booking conversation. "
    "Nothing was sent; reply by hand.",
    "unclear": "Two replies in the booking conversation could not be read with confidence. "
    "Nothing further was sent.",
    "unoffered": "The patient twice picked a time the clinic did not offer. Nothing was booked.",
    "dob_mismatch": "The date of birth in the patient's replies differs from the one on "
    "file. It may be a different person; check before replying.",
    "bad_day": "The patient twice asked for a day outside the booking window.",
    "verification_failed": "The sender's reply to the verification request still did not "
    "identify them. Check who this is before replying.",
    "ambiguous": "The details in the booking conversation match more than one patient, or "
    "only partly match one. Check who this is before replying.",
    "input_blocked": "The patient's reply was blocked by the input guardrail and was not read.",
    "doctor_not_found": "The patient asked for a doctor or specialisation that no active "
    "doctor matches. Nothing was offered.",
    "no_slots": f"No free time within {booking_service.NEAREST_SPAN_DAYS} days of the "
    "requested day. Nothing was offered.",
    "slot_taken": "The time the patient confirmed was taken before it could be booked. "
    "Offer new times by hand.",
    "not_bookable": "The patient confirmed a time, but their record is still missing details "
    "needed to book. Nothing was booked.",
    "closed": "The patient wrote again after this email booking conversation was booked or "
    "handed to staff. Nothing was sent; reply by hand.",
    "form_pending": "The patient replied while their registration form link is still open, "
    "with no details to act on. Nothing was sent; the link still works.",
}


def enabled() -> bool:
    return settings.email_booking_conversation_enabled


def can_auto_reply(email: Email) -> bool:
    """Never answer a machine: two auto-responders answering each other is a
    mail loop."""
    return not email.auto_submitted and not _NO_REPLY.match(email.sender.strip())


def find_mrn(text: str | None) -> str | None:
    match = _MRN.search(text or "")
    return match.group(0).upper() if match else None


def _who(address: str | None) -> str:
    return (address or "").strip().casefold()


# --- linking a reply to its case ----------------------------------------------


async def find_case_for_reply(
    db: AsyncSession, *, sender: str, in_reply_to: str | None, references: str | None
) -> IntakeCase | None:
    """The case an inbound email continues, or None for a new one.

    Headers first: our replies are sent with Graph /reply, so the patient's
    reply carries their original Message-ID in References. That links one
    conversation, not one address, which is what keeps two family members on
    a shared inbox apart. A header match only counts from the address that
    wrote the earlier email; a forward from someone else starts fresh.

    Without headers, the sender address, but only when it has exactly one open
    conversation from the last LINK_FALLBACK_DAYS and at most one patient
    record. Two profiles on one address never link by address.
    """
    who = _who(sender)
    ids = _MESSAGE_ID.findall(f"{in_reply_to or ''} {references or ''}")
    if ids:
        earlier = (
            (await db.execute(select(Email).where(Email.internet_message_id.in_(ids))))
            .scalars()
            .all()
        )
        for email in earlier:
            if _who(email.sender) == who:
                return await db.get(IntakeCase, email.case_id)
        if earlier:
            return None
    cutoff = datetime.now(UTC) - timedelta(days=LINK_FALLBACK_DAYS)
    case_ids = set(
        (
            await db.execute(
                select(EmailConversation.case_id)
                .join(Email, Email.case_id == EmailConversation.case_id)
                .where(
                    func.lower(func.trim(Email.sender)) == who,
                    EmailConversation.stage.in_([s.value for s in OPEN_STAGES]),
                    EmailConversation.updated_at >= cutoff,
                )
            )
        ).scalars()
    )
    if len(case_ids) != 1:
        return None
    profiles = (
        await db.execute(
            select(func.count())
            .select_from(Patient)
            .where(func.lower(func.trim(Patient.email)) == who, Patient.purged_at.is_(None))
        )
    ).scalar_one()
    if profiles > 1:
        return None
    return await db.get(IntakeCase, case_ids.pop())


async def open_for_case(db: AsyncSession, case_id: UUID | None) -> EmailConversation | None:
    if case_id is None:
        return None
    conversation = (
        await db.execute(select(EmailConversation).where(EmailConversation.case_id == case_id))
    ).scalar_one_or_none()
    if conversation is None or conversation.stage not in OPEN_STAGES:
        return None
    return conversation


async def get_or_create(
    db: AsyncSession,
    *,
    case_id: UUID,
    intent: str,
    origin_email_id: UUID,
    patient_id: UUID | None,
    stage: ConversationStage,
) -> tuple[EmailConversation, bool]:
    conversation = (
        await db.execute(select(EmailConversation).where(EmailConversation.case_id == case_id))
    ).scalar_one_or_none()
    if conversation is not None:
        return conversation, False
    conversation = EmailConversation(
        case_id=case_id,
        original_intent=intent,
        origin_email_id=origin_email_id,
        patient_id=patient_id,
        stage=stage.value,
        offered_slots=[],
        clarifications=0,
    )
    db.add(conversation)
    await db.flush()
    return conversation, True


# --- reading the patient's reply ------------------------------------------------


class BookingExtraction(BaseModel):
    """What the model read in the patient's reply. Every value is checked by
    code before anything acts on it."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    dob: str | None = None
    phone: str | None = None
    preferred_day: date | None = None
    part_of_day: Literal["morning", "afternoon", "any"] | None = None
    # Clinic-local wall time, as the offered list shows it.
    chosen_time: datetime | None = None
    doctor_name: str | None = None
    specialisation: str | None = None
    intent: Literal["confirm", "change", "cancel", "question", "unclear"] = "unclear"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator(
        "name",
        "dob",
        "phone",
        "preferred_day",
        "part_of_day",
        "chosen_time",
        "doctor_name",
        "specialisation",
        mode="before",
    )
    @classmethod
    def _null_word_is_null(cls, value: object) -> object:
        # The model writes "chosen_time": "null", and one bad field used to
        # throw the whole extraction away as unclear.
        if isinstance(value, str) and value.strip().casefold() in ("", "null", "none"):
            return None
        return value


_EXTRACT_PROMPT = """BOOKING REPLY EXTRACTION. You read a patient's email to a GP clinic \
about booking an appointment. Extract ONLY what the patient wrote in their NEW MESSAGE. \
Never extract anything from the clinic's own messages, which are shown for context only. \
Do not guess: use null for anything the patient did not write.

The patient's email arrived on {received} (clinic time, Australia/Sydney). Resolve relative \
dates such as "tomorrow", "next Tuesday" or "Friday arvo" against that date. "arvo" means \
afternoon.

TIMES THE CLINIC OFFERED (if the patient picks one, copy its value exactly):
{offered}

THE CLINIC'S LAST MESSAGE TO THE PATIENT (context only):
{last}

THE PATIENT'S NEW MESSAGE:
{new}
{full}
Respond with ONLY a JSON object, no other text, in this exact shape:
{{"name": "<full name or null>", "dob": "<date of birth as YYYY-MM-DD or null>", \
"phone": "<phone number or null>", "preferred_day": "<YYYY-MM-DD or null>", \
"part_of_day": "<morning, afternoon, any, or null>", \
"chosen_time": "<YYYY-MM-DDTHH:MM copied from the offered list, or null>", \
"doctor_name": "<a doctor the patient asked for by name, or null>", \
"specialisation": "<a specialty other than general practice, or null>", \
"intent": "<confirm (picks or accepts a time), change (wants another day or time), \
cancel, question, or unclear>", "confidence": <0.0 to 1.0>}}

JSON:"""


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def named_weekday(day: date | None, text: str, *, today: date) -> date | None:
    """The model resolves "next Wednesday" badly (today, or even yesterday, in
    every black-box sample). When the patient named exactly one weekday and
    the model's day is not that weekday, take the next one after today.
    ponytail: full day names only; add "wed"/"tues" if real mail uses them."""
    if day is None:
        return None
    named = [i for i, name in enumerate(_WEEKDAYS) if re.search(rf"\b{name}\b", text.casefold())]
    if len(named) != 1 or day.weekday() == named[0]:
        return day
    return today + timedelta(days=(named[0] - today.weekday()) % 7 or 7)


_ORDINAL = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "sixth": 5, "6th": 5, "last": -1,
}  # fmt: skip
_ORDINAL_WORD = re.compile(rf"\b({'|'.join(_ORDINAL)})\b")
_ORDINAL_PICK = re.compile(rf"\b({'|'.join(_ORDINAL)})\s+(?:one|option|time|slot|appointment)\b")
_NUMBERED_PICK = re.compile(r"\b(?:option|number|no\.?)\s*#?([1-6])\b")
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")


def slot_named_in(text: str, slots: list[dict]) -> dict | None:
    """The offered slot the patient's own words pick out, or None when they
    do not pick exactly one. Beats the model's chosen_time: gemma2:2b read
    "The second one please" as the sixth slot and 10:30am got booked."""
    text = text.casefold()
    if _ORDINAL_WORD.findall(text) and len(set(_ORDINAL_WORD.findall(text))) > 1:
        return None
    picks = {_ORDINAL[word] for word in _ORDINAL_PICK.findall(text)}
    picks |= {int(n) - 1 for n in _NUMBERED_PICK.findall(text)}
    if picks:
        if len(picks) != 1:
            return None
        (index,) = picks
        return slots[index] if -len(slots) <= index < len(slots) else None
    tz = ZoneInfo(settings.clinic_timezone)
    local = [datetime.fromisoformat(s["start"]).astimezone(tz) for s in slots]
    hits: set[int] = set()
    for hour_text, minute_text, meridiem in _CLOCK.findall(text):
        if not minute_text and not meridiem:
            continue  # a bare number is a date or a count, not a time
        hour, minute = int(hour_text), int(minute_text or 0)
        if meridiem:
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        hits |= {
            i
            for i, t in enumerate(local)
            if t.minute == minute
            and (t.hour == hour or (not meridiem and t.hour % 12 == hour % 12))
        }
    return slots[hits.pop()] if len(hits) == 1 else None


def _local(instant: datetime) -> datetime:
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    return aware.astimezone(ZoneInfo(settings.clinic_timezone))


def _long_date(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B %Y}"


async def extract(
    db: AsyncSession,
    llm: BaseLanguageModel,
    *,
    email: Email,
    conversation: EmailConversation,
    actor: User,
) -> BookingExtraction | None:
    """None when the input guardrail blocked the reply. Unparseable output is
    an empty extraction (intent unclear, confidence 0), never an error."""
    new = email.new_text or reply_parsing.strip_quoted(email.body)
    # strip_quoted already keeps answers written between "> " lines. Only when
    # nothing new is left at all (an inline HTML reply that collapsed onto one
    # line) does the model see the whole body, labelled. A short top-posted
    # "9am works" must not get our quoted offer back in its prompt.
    inline = not new.strip()
    received = _local(email.received_at)
    offered = "\n".join(
        f"- {_local(datetime.fromisoformat(s['start'])):%Y-%m-%dT%H:%M} "
        f"({booking_service.format_slot(datetime.fromisoformat(s['start']))}, "
        f"{booking_service.titled(s['doctor_name'])})"
        for s in conversation.offered_slots
    )
    prompt = _EXTRACT_PROMPT.format(
        received=f"{_long_date(received.date())} at {received:%H:%M}",
        offered=offered or "(none yet)",
        last=conversation.last_outbound_text or "(none yet)",
        new=new or "(empty)",
        full=(
            "\nTHE FULL EMAIL AS RECEIVED (the patient may have answered between the "
            f"clinic's quoted lines, which start with >):\n{email.body}\n"
            if inline
            else ""
        ),
    )
    try:
        raw = await guarded_invoke(db, llm, prompt, actor=actor, route="email.booking_extract")
    except InputBlockedError:
        return None
    text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
    start, end = text.find("{"), text.rfind("}")
    if not 0 <= start < end:
        return BookingExtraction()
    try:
        return BookingExtraction.model_validate_json(text[start : end + 1])
    except ValidationError:
        return BookingExtraction()


# --- what to say ----------------------------------------------------------------

_SIGN_OFF = "\n\nKind regards,\nThe clinic team"


def _hi(name: str | None) -> str:
    return f"Hi {name.split()[0]}," if name else "Hello,"


def verification_text() -> str:
    """Names nobody and repeats nothing from the inquiry: whoever reads this
    inbox may not be who the clinic thinks."""
    return (
        "Hello,\n\n"
        "Thank you for your email. We need more information to verify your profile and "
        "continue with your inquiry. Please reply with:\n"
        f"- {FIELD_LABELS['name']}\n- {FIELD_LABELS['dob']}\n- {FIELD_LABELS['phone']}" + _SIGN_OFF
    )


def ask_details_text(*, name: str | None, missing: list[str], mrn: str | None, day_known: bool):
    items = [FIELD_LABELS[f] for f in missing]
    if not day_known:
        items.append("the day you would prefer to come in")
    lines = [
        _hi(name),
        "",
        "Thank you for contacting the clinic. We have received your appointment request.",
    ]
    if items:
        lines += [
            "",
            "To make the booking we need all of the following. The booking cannot be made "
            "until we have them:",
            *(f"- {item}" for item in items),
        ]
    if mrn:
        lines += ["", f"Your reference number (MRN) is {mrn}. Please quote it when you reply."]
    lines += [
        "",
        "Please do not include any other personal details in your email. The rest of your "
        "registration is completed by phone or at the clinic.",
    ]
    return "\n".join(lines) + _SIGN_OFF


_CONSENT_LINE = (
    "By confirming a time you agree to the clinic keeping the details you have sent us "
    "to arrange your appointment."
)


def offer_payload(days: list[tuple[date, list[booking_service.Slot]]]) -> list[dict]:
    """The offered times as record_sent stores them. UTC instants, so the
    stored value survives any backend that drops the offset (SQLite does)."""
    return [
        {
            "doctor_id": str(doctor_id),
            "doctor_name": doctor,
            "start": start.astimezone(UTC).isoformat(),
        }
        for _, slots in days
        for start, doctor_id, doctor in slots
    ]


def _offer_lines(requested: date, days: list[tuple[date, list[booking_service.Slot]]]):
    wanted = f"{requested:%A} {requested.day} {requested:%B}"
    intro = (
        f"These times are available on {wanted}:"
        if days[0][0] == requested
        else f"We have nothing free on {wanted}. The nearest available times are:"
    )
    return [
        intro,
        *(
            f"- {booking_service.format_slot(start)} with {booking_service.titled(doctor)}"
            for _, slots in days
            for start, _, doctor in slots
        ),
    ]


def offer_text(
    *,
    name: str | None,
    requested: date,
    days: list[tuple[date, list[booking_service.Slot]]],
    missing: list[str],
) -> str:
    lines = [
        _hi(name),
        "",
        *_offer_lines(requested, days),
        "",
        "Please reply with the time that suits you. Nothing has been booked yet.",
    ]
    if missing:
        lines += [
            "",
            "Before we can book, we still need "
            + ", ".join(FIELD_LABELS[f] for f in missing)
            + ".",
        ]
    lines += ["", _CONSENT_LINE]
    return "\n".join(lines) + _SIGN_OFF


def registered_text(
    *,
    name: str | None,
    mrn: str | None,
    requested: date | None,
    days: list[tuple[date, list[booking_service.Slot]]],
) -> str:
    """After the registration form: the MRN, then times, a request for a
    day, or word that staff will find a time."""
    lines = [_hi(name), "", "Thank you for completing the registration form."]
    if mrn:
        lines += ["", f"Your reference number (MRN) is {mrn}. Please quote it when you contact us."]
    if requested is None:
        lines += [
            "",
            "When you would like an appointment, reply to this email with the day you would "
            "prefer to come in.",
        ]
    elif days:
        lines += [
            "",
            *_offer_lines(requested, days),
            "",
            "Please reply with the time that suits you. Nothing has been booked yet.",
            "",
            _CONSENT_LINE,
        ]
    else:
        lines += [
            "",
            f"We have no free times near {requested:%A} {requested.day} {requested:%B}. "
            "A member of our team will be in touch to find a time with you.",
        ]
    return "\n".join(lines) + _SIGN_OFF


def confirmation_text(*, name: str | None, start: datetime, doctor: str, first_visit: bool):
    lines = [
        _hi(name),
        "",
        f"Your appointment is booked for {booking_service.format_slot(start)} with "
        f"{booking_service.titled(doctor)}.",
    ]
    if first_visit:
        lines += [
            "",
            "As this is your first visit, please bring photo ID and arrive 10 minutes early "
            "to complete your registration.",
        ]
    lines += ["", "If you need to change it, reply to this email."]
    return "\n".join(lines) + _SIGN_OFF


def clarify_text(reason: str, conversation: EmailConversation) -> str:
    """Always "Hello,": a changed date of birth may mean a different person
    is replying, so no clarification names anyone."""
    offered = [
        f"- {booking_service.format_slot(datetime.fromisoformat(s['start']))} with "
        f"{booking_service.titled(s['doctor_name'])}"
        for s in conversation.offered_slots
    ]
    if reason == "unoffered":
        body = [
            "The time in your reply is not one of the times we offered. Please reply with "
            "one of these:",
            *offered,
        ]
    elif reason == "dob_mismatch":
        body = [
            "The date of birth in your reply does not match the details we have for this "
            "booking. Please reply to confirm the date of birth of the person the "
            "appointment is for."
        ]
    elif reason == "bad_day":
        body = [
            f"We can book any weekday from today up to {BOOKING_WINDOW_DAYS // 7} weeks ahead. "
            "Please reply with another day."
        ]
    else:
        body = [
            "We could not tell from your reply which day or time you would like. Please "
            "reply with the day you would prefer"
            + (", or one of the times we offered." if offered else ".")
        ]
    return "\n".join(["Hello,", "", *body]) + _SIGN_OFF


# --- one turn -------------------------------------------------------------------


@dataclass
class Turn:
    """What the conversation node does next.

    decision: ask_details | offer | clarify | book | booked | resume | staff
    """

    decision: str
    reason: str | None = None
    text: str | None = None
    next_stage: str | None = None
    offer: list[dict] = field(default_factory=list)
    choice: dict | None = None
    patient: Patient | None = None


def _missing(patient: Patient | None) -> list[str]:
    if patient is None:
        return list(FIELD_LABELS)
    return [f for f in FIELD_LABELS if not getattr(patient, f)]


def _offered(conversation: EmailConversation, chosen: datetime) -> dict | None:
    """The offered slot the patient picked, matched as an instant. A naive
    time is the clinic-local wall time the offered list showed."""
    tz = ZoneInfo(settings.clinic_timezone)
    instant = chosen if chosen.tzinfo is not None else chosen.replace(tzinfo=tz)
    for slot in conversation.offered_slots:
        if datetime.fromisoformat(slot["start"]) == instant:
            return slot
    return None


async def _link(
    db: AsyncSession, conversation: EmailConversation, patient: Patient, *, actor: User
) -> None:
    conversation.patient_id = patient.id
    case = await db.get(IntakeCase, conversation.case_id)
    if case is not None and case.patient_id is None:
        case.patient_id = patient.id
        case.patient_name = patient.name
    if case is not None and case.patient_id == patient.id:
        # Nothing left to confirm: the sender answered the verification.
        await review_routing.complete_open(
            db,
            case_id=case.id,
            kind=TaskType.IDENTITY_REVIEW,
            actor=actor,
            note="Sender verified",
        )


def _staff(conversation: EmailConversation, reason: str) -> Turn:
    conversation.stage = ConversationStage.STAFF.value
    return Turn("staff", reason=reason)


def _failure(conversation: EmailConversation, reason: str) -> Turn:
    """One clarifying reply, then a human."""
    conversation.clarifications += 1
    if conversation.clarifications > 1:
        return _staff(conversation, reason)
    return Turn(
        "clarify",
        reason=reason,
        text=clarify_text(reason, conversation),
        next_stage=conversation.stage,
    )


async def _identify(
    db: AsyncSession,
    conversation: EmailConversation,
    *,
    email: Email,
    fields: IdentityFields,
    actor: User,
    onboard: bool,
) -> tuple[Patient | None, IdentityOutcome]:
    """Match the details against existing records, or, when this is a
    booking, start a provisional profile for a new sender who gave a name.
    Nothing else creates a patient: a stranger asking for records is not one."""
    result = await identity_service.resolve_patient(db, sender=email.sender, fields=fields)
    if result.outcome == IdentityOutcome.MATCHED and result.patient is not None:
        await _link(db, conversation, result.patient, actor=actor)
        return result.patient, result.outcome
    if onboard and result.outcome == IdentityOutcome.NO_MATCH and fields.name:
        patient = await onboarding_service.start_onboarding(
            db, case_id=conversation.case_id, sender=email.sender, fields=fields, actor=actor
        )
        if patient is not None:
            conversation.patient_id = patient.id
        return patient, result.outcome
    return None, result.outcome


async def handle_turn(
    db: AsyncSession,
    llm: BaseLanguageModel,
    *,
    conversation: EmailConversation,
    email: Email,
    actor: User,
    first_turn: bool,
    known: IdentityFields | None = None,
) -> Turn:
    """Read the reply, update the record, decide. Audits the raw extraction
    and the decision. Commits."""
    extraction = await extract(db, llm, email=email, conversation=conversation, actor=actor)
    await record_event(
        db,
        actor=actor,
        case_id=conversation.case_id,
        action="agent.booking_extraction",
        details={
            "email_id": str(email.id),
            "conversation_id": str(conversation.id),
            "blocked": extraction is None,
            "extraction": extraction.model_dump(mode="json") if extraction else None,
        },
    )
    turn = await _decide(
        db,
        conversation=conversation,
        email=email,
        actor=actor,
        extraction=extraction,
        first_turn=first_turn,
        known=known or IdentityFields(),
    )
    await record_event(
        db,
        actor=actor,
        case_id=conversation.case_id,
        action="agent.booking_decision",
        details={
            "email_id": str(email.id),
            "conversation_id": str(conversation.id),
            "decision": turn.decision,
            "reason": turn.reason,
            "stage": conversation.stage,
            "clarifications": conversation.clarifications,
            "offered": [s["start"] for s in turn.offer],
            "choice": turn.choice["start"] if turn.choice else None,
        },
    )
    await db.commit()
    return turn


async def _decide(
    db: AsyncSession,
    *,
    conversation: EmailConversation,
    email: Email,
    actor: User,
    extraction: BookingExtraction | None,
    first_turn: bool,
    known: IdentityFields,
) -> Turn:
    if extraction is None:
        return _staff(conversation, "input_blocked")
    # From the new text only: our own acknowledgement quotes the MRN back.
    new_text = email.new_text or reply_parsing.strip_quoted(email.body)
    fields = IdentityFields(
        name=identity_service._text(extraction.name) or known.name,
        dob=identity_service._as_written(identity_service._past_date(extraction.dob), new_text)
        or known.dob,
        phone=identity_service._text(extraction.phone) or known.phone,
        mrn=find_mrn(new_text),
    )
    patient = await db.get(Patient, conversation.patient_id) if conversation.patient_id else None

    # A reply to the verification request: who is this, now?
    if conversation.stage == ConversationStage.AWAITING_VERIFICATION:
        booking = conversation.original_intent == TaskCategory.APPOINTMENT_REQUEST.value
        # A sign-up that arrived without a name was asked for these details;
        # the reply starts the provisional record, as a booking's does.
        signup = conversation.original_intent == TaskCategory.NEW_PATIENT_ONBOARDING.value
        patient, outcome = await _identify(
            db, conversation, email=email, fields=fields, actor=actor, onboard=booking or signup
        )
        if (outcome == IdentityOutcome.MATCHED or (signup and patient)) and not booking:
            conversation.stage = ConversationStage.VERIFIED.value
            return Turn("resume", patient=patient)
        if patient is None:
            # The verification request was the one ask; this is the second failure.
            return _staff(conversation, "verification_failed")
        conversation.stage = ConversationStage.AWAITING_DETAILS.value
        first_turn = True

    # Who the booking is for.
    if patient is None and fields.name:
        patient, outcome = await _identify(
            db, conversation, email=email, fields=fields, actor=actor, onboard=True
        )
        if outcome == IdentityOutcome.AMBIGUOUS:
            return _staff(conversation, "ambiguous")
    elif patient is not None:
        if fields.dob and patient.dob and fields.dob != patient.dob:
            return _failure(conversation, "dob_mismatch")
        if patient.is_provisional:
            await patient_service.fill_provisional_fields(
                db, patient, actor=actor, name=fields.name, dob=fields.dob, phone=fields.phone
            )

    # On the first turn the classifier already called this a booking request,
    # and "Could I book next Wednesday?" reads as a question to the model.
    if extraction.intent == "cancel" or (extraction.intent == "question" and not first_turn):
        return _staff(conversation, extraction.intent)
    # "Thanks, I'll fill it in tonight" while the registration link is open: a
    # note for staff and nothing sent. Asking for details here would ask for
    # what the form asks, and a second such reply would close the link.
    # Stage unchanged, so the link stays usable.
    if (
        conversation.form_sent_at is not None
        and conversation.form_submitted_at is None
        and patient is None
        and not (fields.name or fields.dob or fields.phone)
        and not (extraction.preferred_day or extraction.chosen_time)
    ):
        return Turn("staff", reason="form_pending")
    # A registered patient is bookable as they are (patient_service.assert_bookable).
    missing = _missing(patient) if patient is None or patient.is_provisional else []
    name = patient.name if patient else fields.name
    trusted = extraction.confidence >= MIN_CONFIDENCE
    if not trusted and not first_turn:
        return _failure(conversation, "unclear")

    # Turn 3: a time from the list we sent. When the patient's words name one
    # slot and they are accepting, those words win over the model's reading.
    named = (
        slot_named_in(new_text, conversation.offered_slots)
        if conversation.offered_slots and extraction.intent == "confirm"
        else None
    )
    if named or (trusted and extraction.chosen_time is not None and conversation.offered_slots):
        choice = named or (
            _offered(conversation, extraction.chosen_time) if extraction.chosen_time else None
        )
        if choice is None:
            return _failure(conversation, "unoffered")
        if missing:
            return Turn(
                "ask_details",
                text=ask_details_text(name=name, missing=missing, mrn=None, day_known=True),
                next_stage=conversation.stage,
            )
        conversation.confirmed_email_id = email.id
        return Turn("book", choice=choice, patient=patient)

    # Turn 2: a day to look at.
    today = _local(email.received_at).date()
    day = named_weekday(
        extraction.preferred_day
        or (extraction.chosen_time.date() if extraction.chosen_time else None),
        new_text,
        today=today,
    )
    if trusted and day is not None:
        if not today <= day <= today + timedelta(days=BOOKING_WINDOW_DAYS):
            return _failure(conversation, "bad_day")
        conversation.preferred_day = day
        # The model has filed the patient's own name as the doctor asked for.
        own = [n.casefold() for n in (fields.name, patient.name if patient else None) if n]
        doctor_name = extraction.doctor_name
        if doctor_name and any(doctor_name.casefold() in n for n in own):
            doctor_name = None
        pool = await booking_service.doctor_pool(
            db,
            patient.id if patient else None,
            doctor_name=doctor_name,
            specialisation=extraction.specialisation,
        )
        if pool is None:
            return _staff(conversation, "doctor_not_found")
        days = await booking_service.offer_times(
            db, actor, pool, day, part_of_day=extraction.part_of_day
        )
        if not days:
            return _staff(conversation, "no_slots")
        return Turn(
            "offer",
            text=offer_text(name=name, requested=day, days=days, missing=missing),
            next_stage=ConversationStage.AWAITING_CHOICE.value,
            offer=offer_payload(days),
        )

    # Turn 1, or a reply that only filled in details: ask for what is left.
    if first_turn or fields.name or fields.dob or fields.phone:
        mrn = (
            patient.mrn
            if patient is not None and _who(patient.email) == _who(email.sender)
            else None
        )
        return Turn(
            "ask_details",
            text=ask_details_text(
                name=name,
                missing=missing,
                mrn=mrn,
                day_known=conversation.preferred_day is not None,
            ),
            next_stage=conversation.stage
            if conversation.offered_slots
            else ConversationStage.AWAITING_DETAILS.value,
        )
    return _failure(conversation, "unclear")


async def record_sent(
    db: AsyncSession,
    conversation_id: str | UUID,
    *,
    text: str | None,
    next_stage: str | None,
    offer: list[dict] | None,
    verification: bool,
    form_link: bool = False,
) -> None:
    """After a reply really went out: what the patient was shown is now what
    the next turn is checked against. Never before, so a reply that failed
    to send can never become "a time we offered"."""
    conversation = await db.get(EmailConversation, UUID(str(conversation_id)))
    if conversation is None:
        return
    conversation.last_outbound_text = text
    if next_stage:
        conversation.stage = next_stage
    if offer:
        conversation.offered_slots = offer
    if verification:
        conversation.verification_sent_at = datetime.now(UTC)
    if form_link:
        # The registration link only opens once its email really went out.
        conversation.form_sent_at = datetime.now(UTC)
    await db.commit()


async def _conversation(db: AsyncSession, conversation_id: str | UUID) -> EmailConversation:
    conversation = await db.get(EmailConversation, UUID(str(conversation_id)))
    if conversation is None:
        raise LookupError(f"email conversation {conversation_id} missing")
    return conversation


async def book_choice(
    db: AsyncSession, *, conversation_id: str | UUID, choice: dict, actor: User
) -> Turn:
    """Turn 3's booking, with nobody approving it (Amin's call, 2026-09-24).

    Re-checked here, not trusted from the turn that read the reply: the
    patient's record must be bookable (patient_service.assert_bookable) and
    the time must still be free now. excl_doctor_overlap is the last word if
    two bookings race for it. Anything short of a clean booking is a human's.
    """
    conversation = await _conversation(db, conversation_id)
    patient = await db.get(Patient, conversation.patient_id) if conversation.patient_id else None
    if patient is None:
        return _staff(conversation, "not_bookable")
    try:
        patient_service.assert_bookable(patient, confirmed_email_id=conversation.confirmed_email_id)
    except patient_service.ProvisionalPatientError:
        return _staff(conversation, "not_bookable")

    start = datetime.fromisoformat(choice["start"])
    doctor = (UUID(choice["doctor_id"]), choice["doctor_name"])
    free = await booking_service.free_on_day(db, actor, [doctor], _local(start).date())
    if start not in {slot for slot, _, _ in free}:
        return _staff(conversation, "slot_taken")

    first_visit = patient.is_provisional
    try:
        appointment = await appointment_service.book_appointment(
            db,
            doctor_id=doctor[0],
            case_id=conversation.case_id,
            time_slot=start,
            actor=actor,
            duration_minutes=settings.default_appointment_duration_minutes,
            appointment_type=(
                AppointmentType.NEW_PATIENT if first_visit else AppointmentType.OTHER
            ),
            internal_notes="Booked by the agent from the patient's email confirmation."
            + (
                " Provisional patient: verify ID and complete registration at arrival."
                if first_visit
                else ""
            ),
            allow_provisional=first_visit,
            commit=False,
        )
    except appointment_service.SlotTakenError:
        # book_appointment rolled the session back; start again from the row.
        conversation = await _conversation(db, conversation_id)
        return _staff(conversation, "slot_taken")
    conversation.stage = ConversationStage.BOOKED.value
    conversation.appointment_id = appointment.id
    return Turn(
        "booked",
        text=confirmation_text(
            name=patient.name, start=start, doctor=doctor[1], first_visit=first_visit
        ),
        patient=patient,
    )
