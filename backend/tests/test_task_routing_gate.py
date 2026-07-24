from app.services.task_routing_gate import TaskRoutingOutcome, evaluate_task_routing_gate
from app.services.task_routing_rules import TaskCategory


def test_high_confidence_auto_routes():
    result = evaluate_task_routing_gate(
        TaskCategory.APPOINTMENT_REQUEST, confidence=0.90, text="I'd like to book an appointment"
    )
    assert result.outcome == TaskRoutingOutcome.AUTO_ROUTED
    assert result.override_reason is None


def test_just_below_auto_threshold_is_flagged():
    result = evaluate_task_routing_gate(
        TaskCategory.APPOINTMENT_REQUEST, confidence=0.89, text="book an appointment"
    )
    assert result.outcome == TaskRoutingOutcome.AUTO_ROUTED_FLAGGED


def test_at_floor_is_flagged():
    result = evaluate_task_routing_gate(
        TaskCategory.APPOINTMENT_REQUEST, confidence=0.70, text="book an appointment"
    )
    assert result.outcome == TaskRoutingOutcome.AUTO_ROUTED_FLAGGED


def test_just_below_floor_is_human_review():
    result = evaluate_task_routing_gate(
        TaskCategory.APPOINTMENT_REQUEST, confidence=0.69, text="book an appointment"
    )
    assert result.outcome == TaskRoutingOutcome.HUMAN_REVIEW
    assert result.override_reason is None


def test_urgent_keyword_forces_human_review_even_at_high_confidence():
    result = evaluate_task_routing_gate(
        TaskCategory.GENERAL_ADMINISTRATIVE, confidence=0.99, text="this is an emergency"
    )
    assert result.outcome == TaskRoutingOutcome.HUMAN_REVIEW
    assert result.override_reason == "urgent_keyword"


def test_complaint_category_forces_human_review_even_at_high_confidence():
    result = evaluate_task_routing_gate(
        TaskCategory.COMPLAINT_ESCALATION, confidence=0.99, text="I want to file a complaint"
    )
    assert result.outcome == TaskRoutingOutcome.HUMAN_REVIEW
    assert result.override_reason == "complaint_category"
