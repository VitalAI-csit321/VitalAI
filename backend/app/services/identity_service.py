"""Who sent this message (build spec §8). The LLM extracts, code decides.

Attaching a stranger's request to a real patient record discloses PHI and has
no recovery path, so the matcher never guesses: anything short of exactly one
full match is AMBIGUOUS or NO_MATCH. Identity only BLOCKS patient-specific
intents; for a general question it is a sender lookup, recorded, and nothing
else (no LLM call).
"""

from __future__ import annotations

import enum
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID

from langchain_core.language_models import BaseLanguageModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.guardrail import InputBlockedError, guarded_invoke
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.task import TaskCategory
from app.models.user import User
from app.services import task_service
from app.services.audit_service import record_event

logger = logging.getLogger(__name__)


class IdentityOutcome(enum.StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


# §8.2. The intents where who the sender is changes what happens next.
PATIENT_SPECIFIC = frozenset(
    {
        TaskCategory.NEW_PATIENT_ONBOARDING,
        TaskCategory.APPOINTMENT_REQUEST,
        TaskCategory.MEDICAL_RECORDS_REQUEST,
        TaskCategory.PRESCRIPTION_RENEWAL,
        TaskCategory.RESULTS_ENQUIRY,
        TaskCategory.REFERRAL_REQUEST,
    }
)
# The only intents a stranger (NO_MATCH) may be onboarded from (§9).
ONBOARDING_INTENTS = frozenset(
    {TaskCategory.NEW_PATIENT_ONBOARDING, TaskCategory.APPOINTMENT_REQUEST}
)


@dataclass(frozen=True)
class IdentityFields:
    name: str | None = None
    dob: date | None = None
    phone: str | None = None

    def present(self) -> list[str]:
        return [k for k, v in asdict(self).items() if v]


@dataclass(frozen=True)
class IdentityResult:
    outcome: IdentityOutcome
    patient: Patient | None = None


_PROMPT = """Extract the IDENTITY DETAILS the sender gives about themselves in the \
email below. Do not guess and do not infer anything that is not written.

Respond with ONLY a JSON object, no other text, in this exact shape:
{{"name": "<full name or null>", "dob": "<date of birth as YYYY-MM-DD or null>", \
"phone": "<phone number or null>"}}

EMAIL:
{content}

JSON:"""


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _past_date(value: object) -> date | None:
    """Only a real calendar date before today. "next Tuesday" is not a DOB."""
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        # The prompt asks for YYYY-MM-DD, but the model echoes the format the
        # sender wrote, and a patient here writes 15/10/1989. Dropping that
        # silently cost the DOB on otherwise perfect emails, and without a DOB
        # there is no full match, so every one of them held for staff.
        # ponytail: day-first, the same assumption the frontend's date fields
        # make; 05/10/1989 reads as 5 October, not 10 May.
        match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
        if match is None:
            return None
        day, month, year = (int(part) for part in match.groups())
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
    return parsed if parsed < date.today() else None


async def extract_identity_fields(
    db: AsyncSession, llm: BaseLanguageModel, content: str, *, actor: User
) -> IdentityFields:
    """Unparseable or blocked output means no fields, never an error."""
    try:
        raw = await guarded_invoke(
            db, llm, _PROMPT.format(content=content), actor=actor, route="email.identity_extract"
        )
    except InputBlockedError:
        return IdentityFields()
    text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
    start, end = text.find("{"), text.rfind("}")
    try:
        parsed = json.loads(text[start : end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        return IdentityFields()
    return IdentityFields(
        name=_text(parsed.get("name")),
        dob=_past_date(parsed.get("dob")),
        phone=_text(parsed.get("phone")),
    )


def _name(value: str | None) -> str | None:
    return " ".join(value.casefold().split()) or None if value else None


def _email(value: str | None) -> str | None:
    return value.strip().casefold() or None if value else None


def _phone(value: str | None) -> str | None:
    # ponytail: AU-centric, the last 9 digits ignore a 0 or +61 prefix. Swap in
    # a real phone-number library if numbers go international.
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 9 else None


async def resolve_patient(
    db: AsyncSession, *, sender: str | None, fields: IdentityFields
) -> IdentityResult:
    """Exact, normalised matching only. Full match = name AND DOB AND (sender
    email OR phone). Exactly one full match is MATCHED; more than one, or a
    partial match on name, sender email or phone, is AMBIGUOUS."""
    name, email, phone = _name(fields.name), _email(sender), _phone(fields.phone)
    # Purged rows are anonymised and never candidates; provisional ones are,
    # so a new patient's follow-up email finds their record, not a duplicate.
    # ponytail: a full scan of live patients, fine at clinic scale; move the
    # normalisation into indexed columns if the table reaches tens of thousands.
    patients = (
        (await db.execute(select(Patient).where(Patient.purged_at.is_(None)))).scalars().all()
    )
    full, partial = [], False
    for p in patients:
        name_hit = name is not None and _name(p.name) == name
        email_hit = email is not None and _email(p.email) == email
        phone_hit = phone is not None and _phone(p.phone) == phone
        if name_hit and fields.dob is not None and p.dob == fields.dob and (email_hit or phone_hit):
            full.append(p)
        partial = partial or name_hit or email_hit or phone_hit
    if len(full) == 1:
        return IdentityResult(IdentityOutcome.MATCHED, full[0])
    if full or partial:
        return IdentityResult(IdentityOutcome.AMBIGUOUS)
    return IdentityResult(IdentityOutcome.NO_MATCH)


async def identify_sender(
    db: AsyncSession,
    *,
    llm: BaseLanguageModel,
    intent: TaskCategory | None,
    case_id: UUID | None,
    sender: str | None,
    content: str | None,
    actor: User,
) -> tuple[IdentityResult, IdentityFields]:
    """Resolve, record, and for a patient-specific MATCHED link the case.

    General intents make no LLM call: a sender lookup only, which can never
    be a full match, so it blocks nothing and creates nothing.
    """
    specific = intent in PATIENT_SPECIFIC
    case = await db.get(IntakeCase, case_id) if case_id is not None else None
    linked = await db.get(Patient, case.patient_id) if case and case.patient_id else None
    fields = IdentityFields()
    if linked is not None:
        # Staff already attached this case to a patient; nothing to resolve.
        result = IdentityResult(IdentityOutcome.MATCHED, linked)
    else:
        if specific:
            fields = await extract_identity_fields(db, llm, content or "", actor=actor)
        result = await resolve_patient(db, sender=sender, fields=fields)
        if specific and result.outcome == IdentityOutcome.MATCHED and case is not None:
            case.patient_id = result.patient.id
            case.patient_name = result.patient.name
    await record_event(
        db,
        actor=actor,
        case_id=case_id,
        action="agent.identity_resolved",
        details={
            "outcome": result.outcome.value,
            "intent": intent.value if intent else None,
            "patient_id": str(result.patient.id) if result.patient else None,
            # Which fields the sender gave, never their values: audit details
            # are hash-chained and cannot be scrubbed later.
            "fields_present": fields.present(),
            "extracted": specific and linked is None,
        },
    )
    await db.commit()
    return result, fields


_HOLD_REASONS = {
    IdentityOutcome.AMBIGUOUS: (
        "Sender identity not confirmed: the details match more than one patient, or only "
        "partly match one. Check who this is before replying."
    ),
    IdentityOutcome.NO_MATCH: (
        "No patient record matches the sender. Nothing was drafted and no patient was created."
    ),
    IdentityOutcome.MATCHED: (
        "The sender matches a provisional patient, who cannot use this service until staff "
        "complete their registration."
    ),
}


async def hold_for_staff(db: AsyncSession, task_id: str | UUID, outcome: IdentityOutcome) -> None:
    await task_service.hold_for_staff(db, task_id, _HOLD_REASONS[outcome])
