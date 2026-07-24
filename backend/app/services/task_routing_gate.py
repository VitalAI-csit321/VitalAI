"""Confidence gate for task routing (FR-GOV-02), reusing the existing
3-tier shape from app.rag.gating. Pure function of a category + confidence
score, no DB, no LLM call. Two hard overrides bypass the threshold logic
entirely: an urgent-content keyword match (reuses triage_service's own
URGENT_KEYWORDS check) and the Complaint/Escalation category — both per
docs/superpowers/specs/2026-07-20-ai-task-routing-design.md section 12.

This gate is deliberately separate from app.rag.gating's
SUFFICIENCY_FLOOR/CONFIDENCE_THRESHOLD, which gates RAG draft-grounding
sufficiency, not task-routing confidence. Do not conflate the two.
"""

import enum

from pydantic import BaseModel

from app.config import settings
from app.services.task_routing_rules import TaskCategory
from app.services.triage_service import URGENT_KEYWORDS, matches_any


class TaskRoutingOutcome(enum.StrEnum):
    AUTO_ROUTED = "auto_routed"
    AUTO_ROUTED_FLAGGED = "auto_routed_flagged"
    HUMAN_REVIEW = "human_review"


class TaskRoutingGateResult(BaseModel):
    outcome: TaskRoutingOutcome
    override_reason: str | None


def evaluate_task_routing_gate(
    category: TaskCategory, confidence: float, text: str
) -> TaskRoutingGateResult:
    """Decide whether a classified task auto-routes, auto-routes but gets
    flagged for audit sampling, or goes straight to the human reviewer queue.
    """
    if matches_any(text.lower(), URGENT_KEYWORDS):
        return TaskRoutingGateResult(
            outcome=TaskRoutingOutcome.HUMAN_REVIEW, override_reason="urgent_keyword"
        )
    if category == TaskCategory.COMPLAINT_ESCALATION:
        return TaskRoutingGateResult(
            outcome=TaskRoutingOutcome.HUMAN_REVIEW, override_reason="complaint_category"
        )

    if confidence >= settings.task_routing_auto_threshold:
        outcome = TaskRoutingOutcome.AUTO_ROUTED
    elif confidence >= settings.task_routing_floor:
        outcome = TaskRoutingOutcome.AUTO_ROUTED_FLAGGED
    else:
        outcome = TaskRoutingOutcome.HUMAN_REVIEW

    return TaskRoutingGateResult(outcome=outcome, override_reason=None)
