"""Onboarding a sender nobody can identify (build spec §9.0).

Runs only for NO_MATCH plus an onboarding intent (§8.2). Creates a provisional
patient, records the consent their email implies (PENDING, never CAPTURED),
and drafts a reply asking only for the identity and contact details still
missing. Never for health or financial details: email is not a secure channel,
and draft_critic enforces that on the draft itself.
"""

from uuid import UUID

from langchain_core.language_models import BaseLanguageModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.guardrail import guarded_invoke
from app.models.email import Email
from app.models.patient import Patient
from app.models.user import User
from app.services import consent_service, patient_service
from app.services.identity_service import IdentityFields

BRANCH = "onboarding"

# The only fields a reply may ask for, and how to say them. Health, financial
# and insurance fields are deliberately absent.
ASKABLE = {"dob": "date of birth", "phone": "phone number"}

_PROMPT = """You are a clinic administrator replying to someone emailing a GP clinic \
for the first time. Write a short, polite reply that thanks them and asks them to \
reply with the details listed below so the clinic can set up their record.

ASK ONLY FOR: {requested}
Do not ask for, or invite them to send, any health, medical, Medicare, insurance or \
payment details by email. Say that the rest of the registration is completed by phone \
or in the clinic. Do not offer, suggest or confirm any appointment time.

ORIGINAL EMAIL SUBJECT: {subject}
ORIGINAL EMAIL BODY: {body}

{revision}REPLY:"""


async def start_onboarding(
    db: AsyncSession,
    *,
    case_id: UUID | None,
    sender: str | None,
    fields: IdentityFields,
    actor: User,
) -> Patient | None:
    """None when there is no name to file the record under: Patient.name is
    NOT NULL, and inventing one would be worse than handing this to staff."""
    if not fields.name or case_id is None:
        return None
    patient = await patient_service.create_provisional_patient(
        db,
        case_id=case_id,
        name=fields.name,
        email=sender,
        phone=fields.phone,
        dob=fields.dob,
        actor=actor,
    )
    await consent_service.create_consent_record(
        db,
        case_id,
        actor,
        consent_type=consent_service.IMPLIED_INBOUND_CONTACT,
        notes="Implied by the patient contacting the clinic. Explicit consent is still required.",
    )
    return patient


def fields_to_request(patient: Patient) -> list[str]:
    """Which ASKABLE fields are still missing. patient_service owns what
    "missing" means for the profile; dob is not a PROFILE_FIELDS column."""
    missing = set(patient_service.missing_profile_fields(patient))
    if patient.dob is None:
        missing.add("dob")
    return [f for f in ASKABLE if f in missing]


async def draft_onboarding_reply(
    db: AsyncSession,
    llm: BaseLanguageModel,
    *,
    email: Email,
    requested: list[str],
    actor: User,
    feedback: str | None = None,
) -> str:
    from app.rag.answer import revision_block

    result = await guarded_invoke(
        db,
        llm,
        _PROMPT.format(
            requested=", ".join(ASKABLE[f] for f in requested)
            or "nothing further; confirm the clinic has their details",
            subject=email.subject,
            body=email.body,
            revision=revision_block(feedback),
        ),
        actor=actor,
        route="email.onboarding_draft",
    )
    return result if isinstance(result, str) else getattr(result, "content", str(result))
