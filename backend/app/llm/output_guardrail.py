"""Output-side restricted-terms guardrail (FR-GOV-03).

Scoped to patient-facing email drafts ONLY (see
docs/superpowers/specs/2026-07-27-email-governance-pipeline-design.md) --
never wraps /rag/query, which is clinician-facing and legitimately needs to
say "diagnosis"/"prescription"/"treatment plan". Same fail-safe shape as
app.llm.guardrail's input guardrail: on a match, no draft is used, a
governance.output_blocked AuditEvent is written (matched term only, never
the full draft), and OutputBlockedError is raised so the caller routes to
human review instead of sending.

Term list is Ariana's actual restricted-terms table. Known gap, not built
here: the table's "Sensitive Data: references to other patients" row isn't
literal-term-matchable -- it needs real cross-referencing, not substring
matching. Flagged, not silently dropped.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.audit_service import record_event
from app.services.triage_service import matches_any

logger = logging.getLogger(__name__)

RESTRICTED_TERMS: tuple[str, ...] = (
    # Medical diagnoses
    "cancer",
    "tumour",
    "diabetes diagnosis",
    "infection confirmed",
    "mental disorder",
    # Medications
    "insulin",
    "antibiotics",
    "antidepressants",
    "dosage instructions",
    # Clinical terminology
    "diagnosis",
    "prognosis",
    "treatment plan",
    "prescription",
    "clinical findings",
    # Medical advice phrasing
    "you should take",
    "you must",
    "start medication",
    "this condition requires",
    # Test/scan interpretation
    "your test shows",
    "scan indicates",
    "results confirm",
    # Urgency language
    "critical condition",
    "life-threatening",
    "emergency",
    # Internal system terms
    "escalation",
    "triage",
    "risk tier",
    "system flag",
    # Error/uncertainty
    "system error",
    "data issue",
    "we are not sure",
    # Legal language
    "liability",
    "malpractice",
    "legal responsibility",
)


# Amin's call (2026-10-11): the clinic's own documents say "call 000 in an
# emergency", so a word match on "emergency" threw away correct replies to
# "what do I do after hours?". These are the clinic stating its own facts, not
# the model judging a patient's condition. Every other term still applies to
# the same sentence.
_SAFE_WORDING = re.compile(r"emergency (?:department|contact|care)|mental health treatment plan")
_SENTENCE_WITH_000 = re.compile(r"[^.!?\n]*\b000\b[^.!?\n]*")


def _without_safe_wording(text: str) -> str:
    text = _SAFE_WORDING.sub("", text.lower())
    return _SENTENCE_WITH_000.sub(lambda m: m.group(0).replace("emergency", ""), text)


class OutputBlockedError(Exception):
    """Raised when check_output() blocks a draft. Carries the matched term
    for the caller's own logging/testing only -- never surface matched_term
    (or str(exc)) to a patient; the caller must route to human review with a
    fixed generic message instead.
    """

    def __init__(self, matched_term: str) -> None:
        self.matched_term = matched_term
        super().__init__(f"Output blocked: matched restricted term {matched_term!r}")


def _first_match(text: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        if matches_any(text, (term,)):
            return term
    return None


def restricted_term(text: str) -> str | None:
    """The first restricted term in text, or None. No audit event: for a
    caller deciding whether to use a piece of text at all."""
    return _first_match(_without_safe_wording(text), RESTRICTED_TERMS)


async def check_output(db: AsyncSession, text: str, *, actor: User, case_id: UUID | None) -> None:
    """Raise OutputBlockedError if text contains a restricted term.

    On a match: no draft is used, a governance.output_blocked AuditEvent is
    written (matched term only), and the error propagates. A failed audit
    write is caught and logged rather than propagated -- mirroring
    app.auth.dependencies._deny() and app.llm.guardrail.guarded_invoke()'s
    fail-safe shape: a genuine block must always still raise, never surface
    as an unrelated audit-write 500.
    """
    matched = restricted_term(text)
    if matched is None:
        return
    try:
        await record_event(
            db,
            actor=actor,
            case_id=case_id,
            action="governance.output_blocked",
            details={"matched_term": matched},
        )
        await db.commit()
    except Exception:
        logger.exception("failed to record governance.output_blocked audit event")
        await db.rollback()
    raise OutputBlockedError(matched)
