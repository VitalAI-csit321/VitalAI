"""Rules-based triage classifier — Phase 1.

In Phase 3 this will be replaced by an NLP urgency classifier behind a
LangGraph node, and the abstraction will move to app.agents.triage.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import ConsentRecord, ConsentStatus
from app.models.triage import TriageCategory, TriageResult
from app.models.user import User
from app.schemas.triage import TriageRequest, TriageResponse
from app.services.audit_service import record_event
from app.services.consent_service import get_consent_for_case
from app.services.routing_rules import decide

URGENT_KEYWORDS: tuple[str, ...] = (
    "emergency",
    "urgent",
    "immediate",
    "critical",
    "chest pain",
    "difficulty breathing",
    "unconscious",
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

    WARNING: negation is not handled. "not urgent" will match the URGENT_KEYWORDS
    list and incorrectly escalate. This is a known limitation of the rules-based
    classifier and will be addressed when classify() is replaced by the LangGraph
    NLP pipeline in Phase 3.
    """
    return any(kw in text for kw in keywords)


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


# Phase 3: replace with app.agents.triage_agent.classify_with_graph (LangGraph orchestration)
async def classify(db: AsyncSession, request: TriageRequest, actor: User) -> TriageResponse:
    await _assert_consent(db, request.case_id)

    haystack = request.contact_reason.lower() + " " + " ".join(k.lower() for k in request.keywords)

    has_urgent = matches_any(haystack, URGENT_KEYWORDS)
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
