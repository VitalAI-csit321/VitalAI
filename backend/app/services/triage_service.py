"""Rules-based triage classifier for the manual `POST /triage` endpoint.

Superseded for live email/call ingestion by app.services.content_classifier's
LLM-based classifier (FR-TRIAGE-01), which those pipelines call directly.
This module stays in use for two other reasons: `POST /triage` is still a
real, tested manual-classification path, and matches_any/is_urgent/
ConsentGatingError defined here are reused by app.llm.guardrail and
app.services.task_routing_gate. Don't delete this file assuming it's dead.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import ConsentRecord, ConsentStatus
from app.models.triage import TriageCategory, TriageResult
from app.models.user import User
from app.schemas.triage import TriageRequest, TriageResponse
from app.services.audit_service import record_event
from app.services.consent_service import get_consent_for_case
from app.services.routing_rules import decide

# Words that only say "this is urgent". A negation just before one ("not urgent",
# "non-urgent", "isn't an emergency") cancels it; see is_urgent().
URGENT_KEYWORDS: tuple[str, ...] = (
    "emergency",
    "urgent",
    "immediate",
    "critical",
)

# Symptoms that mean a person should see this now. Never cancelled by a negation:
# "can't breathe" contains one, and a false alarm only costs a human a look.
# Taken from healthdirect's triple-zero guidance, not tuned against any test set:
# healthdirect.gov.au/calling-triple-zero, /symptoms-of-serious-illness-in-babies-and-children,
# /anaphylaxis, /drug-overdose, /are-you-experiencing-suicidal-thoughts.
# Substring matched, so each is a phrase that is rare in routine mail ("burns" is a
# surname, "000" is in phone numbers, "epipen" is in routine script renewals).
RED_FLAG_PHRASES: tuple[str, ...] = (
    # chest pain
    "chest pain",
    "pain in my chest",
    "pain in his chest",
    "pain in her chest",
    "tight chest",
    "chest tightness",
    # breathing problems
    "difficulty breathing",
    "trouble breathing",
    "struggling to breathe",
    "can't breathe",
    "cannot breathe",
    "can not breathe",
    "not breathing",
    "short of breath",
    "shortness of breath",
    "turning blue",
    "blue lips",
    "lips are blue",
    # loss of consciousness, collapse, very drowsy
    "unconscious",
    "unresponsive",
    "passed out",
    "blacked out",
    "faint",
    "collapse",
    "won't wake",
    "wont wake",
    "can't wake",
    "cannot wake",
    "hard to wake",
    "not waking",
    "very drowsy",
    "floppy",
    # stroke
    "stroke",
    "slurred",
    "face drooping",
    "face is drooping",
    "drooping face",
    "trouble speaking",
    "weakness on one side",
    "numb on one side",
    # seizure
    "seizure",
    "convulsi",
    "having a fit",
    # fall, injury
    "fallen",
    "had a fall",
    "a bad fall",
    "fell down",
    "fell over",
    "fell off",
    "can't get up",
    "cannot get up",
    "can not get up",
    "unable to get up",
    "head injury",
    "hit my head",
    "hit his head",
    "hit her head",
    "severe burn",
    "badly burned",
    "badly burnt",
    "snake bite",
    "snakebite",
    "stabbed",
    "assaulted",
    # bleeding
    "bleeding",
    "vomiting blood",
    "coughing up blood",
    # anaphylaxis
    "anaphyla",
    "throat swelling",
    "swelling of the throat",
    "throat is swelling",
    "swollen throat",
    "swollen tongue",
    "tongue is swelling",
    # overdose, poisoning
    "overdose",
    "too many tablets",
    "too many pills",
    "too much medication",
    "too many of his",
    "too many of her",
    "too many of my",
    "poison",
    "swallowed",
    # suicide, self-harm
    "suicid",
    "kill myself",
    "end my life",
    "self-harm",
    "self harm",
    "hurt myself",
    # ...and indirectly, which is how most people write it. Not bare "ending it":
    # that is inside "sending it" and "attending it".
    "want to die",
    "want to be alive",
    "want to live like this",
    "want to live anymore",
    "thinking about ending it",
    "thinking of ending it",
    "end it all",
    "better off without me",
    "better off dead",
    "no reason to live",
    "take my own life",
    "taking my own life",
    # children
    "rash that doesn't fade",
    "rash that does not fade",
    "non-blanching",
    "bulging fontanelle",
)

# Chest symptoms written with words in between, which no literal phrase above matches:
# "pain in the middle of my chest", "my chest is hurting", "pressure in my chest".
# Symptom up to six words before "chest", or up to three words after it.
_CHEST_SYMPTOM = (
    r"(?:pains?|painful|hurts?|hurting|ache|aching|pressure|tight|tightness|heavy|heaviness"
    r"|squeez\w*|crushing|discomfort)"
)
_CHEST_RED_FLAG = re.compile(
    rf"\b{_CHEST_SYMPTOM}\b(?:\W+\w+){{0,6}}?\W+chest\b"
    rf"|\bchest\b(?:\W+\w+){{0,3}}?\W+{_CHEST_SYMPTOM}\b"
)

# A negation up to two words before a generic urgency word: "not urgent",
# "not an emergency", "nothing really urgent", "non-urgent".
_NEGATED = re.compile(
    r"\b(?:not|no|non|never|nothing|isn't|isnt|wasn't|aren't|don't|dont|doesn't)"
    r"(?:\s+\w+){0,2}[\s-]*$"
)

TIME_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "today",
    "asap",
    "soon",
    "worried",
    "concerned",
    "follow-up",
    "test results",
    "referral",
)


class ConsentGatingError(Exception):
    """Raised when triage is attempted without valid consent."""


def matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Substring match — handles multi-word phrases like 'chest pain'.

    Deliberately literal, with no negation handling: the input and output guardrails
    and the reminder screen use it, and "do not ignore previous instructions" must
    still match there. The urgent scan goes through is_urgent() instead.
    """
    return any(kw in text for kw in keywords)


def is_urgent(text: str) -> bool:
    """True if the text names a red-flag symptom, or uses an urgency word that is
    not negated. Red flags are never negated away: missing an emergency costs far
    more than a human reading one routine email."""
    text = text.lower().replace("’", "'")
    if matches_any(text, RED_FLAG_PHRASES) or _CHEST_RED_FLAG.search(text):
        return True
    for kw in URGENT_KEYWORDS:
        start = text.find(kw)
        while start != -1:
            if not _NEGATED.search(text[max(0, start - 40) : start]):
                return True
            start = text.find(kw, start + 1)
    return False


async def _assert_consent(db: AsyncSession, case_id) -> ConsentRecord:
    """Return the consent record if captured; raise ConsentGatingError otherwise."""
    record = await get_consent_for_case(db, case_id)
    if record is None:
        raise ConsentGatingError(
            f"No consent record found for case {case_id}. "
            "Consent must be captured before triage can proceed."
        )
    if record.status == ConsentStatus.WITHDRAWN:
        raise ConsentGatingError(
            f"Consent for case {case_id} has been withdrawn. Triage is not permitted."
        )
    if record.status != ConsentStatus.CAPTURED:
        raise ConsentGatingError(
            f"Consent for case {case_id} is in state '{record.status.value}'. "
            "Triage requires captured consent."
        )
    return record


async def classify(db: AsyncSession, request: TriageRequest, actor: User) -> TriageResponse:
    await _assert_consent(db, request.case_id)

    haystack = request.contact_reason.lower() + " " + " ".join(k.lower() for k in request.keywords)

    has_urgent = is_urgent(haystack)
    has_time_sensitive = matches_any(haystack, TIME_SENSITIVE_KEYWORDS)
    has_patient_flags = len(request.patient_priority_flags) > 0
    insufficient_info = len(haystack.split()) < 3

    # Patient priority flags escalate; they do not reduce confidence.
    if has_urgent or (has_patient_flags and has_time_sensitive):
        category = TriageCategory.IMMEDIATE
        confidence = 0.9
        rationale = "Urgent keyword or flagged-patient + time-sensitive — immediate escalation"
    elif has_time_sensitive or has_patient_flags:
        category = TriageCategory.TIME_SENSITIVE
        confidence = 0.7
        rationale = "Time-sensitive keyword or patient priority flag — human review"
    elif insufficient_info:
        category = TriageCategory.LOW_CONFIDENCE
        confidence = 0.4
        rationale = "Insufficient information — manual review required"
    else:
        category = TriageCategory.ROUTINE
        confidence = 0.8
        rationale = "Routine administrative matter — normal workflow"

    routing_action, target_queue, escalated = decide(category)

    triage_row = TriageResult(
        case_id=request.case_id,
        category=category,
        confidence=confidence,
        rationale=rationale,
    )
    db.add(triage_row)
    await db.flush()

    await record_event(
        db,
        case_id=request.case_id,
        actor=actor,
        action="triage.performed",
        details={
            "triage_id": str(triage_row.id),
            "category": category.value,
            "confidence": confidence,
            "escalated": escalated,
        },
    )
    await db.commit()
    await db.refresh(triage_row)

    return TriageResponse(
        triage_id=triage_row.id,
        case_id=request.case_id,
        category=category,
        confidence=confidence,
        rationale=rationale,
        routing_action=routing_action,
        target_queue=target_queue,
        escalated=escalated,
    )
