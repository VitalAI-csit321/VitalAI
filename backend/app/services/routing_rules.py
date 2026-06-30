"""Canonical mapping from triage category to routing action and queue.

Single source of truth used by both triage_service (to compute the
predicted routing in the triage API response) and routing_service
(to persist the actual RoutingDecision row).
"""

from app.models.routing import RoutingAction
from app.models.triage import TriageCategory


def decide(category: TriageCategory) -> tuple[RoutingAction, str, bool]:
    """Map a triage category to (routing_action, target_queue, escalated)."""
    if category == TriageCategory.IMMEDIATE:
        return RoutingAction.DIRECT_ESCALATION, "escalation_immediate", True
    if category == TriageCategory.TIME_SENSITIVE:
        return RoutingAction.HUMAN_REVIEW, "priority_review", True
    if category == TriageCategory.LOW_CONFIDENCE:
        return RoutingAction.HUMAN_REVIEW, "low_confidence_review", True
    return RoutingAction.ADMIN_WORKFLOW, "admin_routine", False
