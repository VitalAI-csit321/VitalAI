"""Acknowledging a request for a copy of a patient's records (build spec §11).

The agent never puts clinical content in an email. It acknowledges the
request, says what happens next, and hands the case to a human; consent only
decides which of the two acknowledgements it drafts.

Both are templates, not generations. There is nothing to generate here, only a
thing to state, so this branch makes no LLM call at all. Nothing in either
template invents a URL, a form link, a reference number or a date: "a member of
the team will be in touch" is a promise the clinic can actually keep.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import ConsentStatus
from app.services import consent_service

BRANCH = "records"

_INTRO = "Thank you for your request for a copy of your medical records."
_NOT_ATTACHED = "No records are attached to this email."
_SIGN_OFF = "Kind regards,\nThe clinic team"


async def has_explicit_consent(db: AsyncSession, patient_id: UUID | None) -> bool:
    """Whether this PATIENT has given consent a person actually signed.

    Asked about the patient, not the case (spec G.11). ingest_email opens a new
    case for every message and the Outlook connector passes no case_id, so a
    real records email always lands on a case with no consent record: the
    case-level question could never be answered yes in production, and patients
    who had already consented were told they still had to.

    The same rule patient_service.promote_patient applies: any CAPTURED record
    whose type is not the implied one. Deliberately not
    triage_service._assert_consent, which raises when there is no record at
    all: that is an outcome here, not an error (Appendix F.2).

    An implied record is the clinic noting that someone emailed in. It is
    nobody's authority to release their file, whichever case it sits on.
    """
    if patient_id is None:
        return False
    records = await consent_service.list_consents_for_patient(db, patient_id)
    return any(
        r.status == ConsentStatus.CAPTURED
        and r.consent_type != consent_service.IMPLIED_INBOUND_CONTACT
        for r in records
    )


def draft_records_reply(*, name: str | None, consent_on_file: bool) -> str:
    greeting = f"Hi {name.split()[0] if name else 'there'},"
    if consent_on_file:
        body = (
            "We have your consent on file. A member of our team will verify your identity "
            "and arrange the release with you, and will be in touch."
        )
    else:
        body = (
            "Before we can release them we need your written consent. A member of our team "
            "will be in touch to go through what we need from you."
        )
    return f"{greeting}\n\n{_INTRO} {body}\n\n{_NOT_ATTACHED}\n\n{_SIGN_OFF}"
