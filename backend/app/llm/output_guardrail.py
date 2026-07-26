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


async def check_output(db: AsyncSession, text: str, *, actor: User, case_id: UUID | None) -> None:
    """Raise OutputBlockedError if text contains a restricted term.

    On a match: no draft is used, a governance.output_blocked AuditEvent is
    written (matched term only), and the error propagates. A failed audit
    write is caught and logged rather than propagated -- mirroring
    app.auth.dependencies._deny() and app.llm.guardrail.guarded_invoke()'s
    fail-safe shape: a genuine block must always still raise, never surface
    as an unrelated audit-write 500.
    """
    matched = _first_match(text.lower(), RESTRICTED_TERMS)
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
