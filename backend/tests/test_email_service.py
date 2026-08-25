import json
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.email import EmailIngestRequest
from app.services import email_service


class _FakeLLM:
    """Answers the classifier's canned response, and answers WORTHY to
    whatever the reply-worthiness gate's separate LLM call asks -- these
    tests aren't exercising the gate itself (see test_reply_gate.py), they
    just need it out of the way.
    """

    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


@pytest.mark.asyncio
async def test_ingest_email_creates_case_and_auto_routes(db_session, front_desk_user, monkeypatch):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.95})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Need an appointment",
        body="Can I book an appointment for next week?",
    )

    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    assert email.subject == "Need an appointment"
    assert task.source.value == "email"
    assert task.category.value == "appointment_request"
    assert task.target_role.value == "front_desk"
    assert gate.outcome.value == "auto_routed"
    assert confidence == 0.95


@pytest.mark.asyncio
async def test_ingest_email_low_confidence_goes_to_human_review(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.4})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="???",
        body="not sure what this is about",
    )

    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    assert gate.outcome.value == "human_review"
    assert task.status.value == "pending"
    assert confidence == 0.4


@pytest.mark.asyncio
async def test_ingest_email_complaint_always_routes_to_human_review(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "complaint_escalation", "confidence": 0.98})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Formal complaint",
        body="I am extremely unhappy with my last visit.",
    )

    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    assert gate.outcome.value == "human_review"
    assert gate.override_reason == "complaint_category"
    assert task.target_role.value == "operator"


@pytest.mark.asyncio
async def test_draft_reply_skipped_for_human_review_outcome(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "complaint_escalation", "confidence": 0.9})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Complaint",
        body="I am unhappy.",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.draft_text is None
    assert outcome.sent is False


@pytest.mark.asyncio
async def test_draft_reply_non_clinical_category_uses_plain_generation(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Opening hours",
        body="What time do you open on Saturdays?",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("We open at 9am on Saturdays.", True)),
    ):
        outcome = await email_service.draft_reply(
            db_session, task, email, front_desk_user, gate, confidence
        )

    assert outcome.draft_text == "We open at 9am on Saturdays."
    # confidence 0.95 >= task_routing_auto_threshold (0.90) => sent immediately, no approval needed
    assert outcome.sent is True
    assert outcome.approval_id is None


@pytest.mark.asyncio
async def test_draft_reply_blocked_by_output_guardrail_routes_to_human(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Question",
        body="What time do you open?",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("Your prescription is ready for pickup.", True)),
    ):
        outcome = await email_service.draft_reply(
            db_session, task, email, front_desk_user, gate, confidence
        )

    assert outcome.blocked is True
    assert outcome.sent is False
    assert outcome.draft_text is None


def _org_chunk(content: str, score: float):
    from uuid import uuid4

    from app.rag.retrieval import RetrievedChunk

    return RetrievedChunk(
        chunk_id=uuid4(),
        patient_id=None,
        access_scope="general",
        source_document_id=uuid4(),
        doc_type="clinic_identity",
        chunk_index=0,
        attachment_uri=None,
        content=content,
        score=score,
        distance=1 - score,
    )


@pytest.mark.asyncio
async def test_org_grounded_reply_includes_retrieved_context_when_sufficient(
    db_session, front_desk_user, monkeypatch
):
    """Above sufficiency_floor: the org-wide chunk content must reach the LLM
    prompt, so a general enquiry can be answered with real clinic facts
    instead of an ungrounded guess."""
    captured_prompt = {}

    class _CapturingLLM:
        async def ainvoke(self, prompt: str) -> str:
            captured_prompt["text"] = prompt
            return "Our hours are Mon-Fri 8:30-6:00."

    monkeypatch.setattr(
        "app.rag.retrieval.retrieve",
        AsyncMock(return_value=[_org_chunk("Monday to Friday: 8:30 AM to 6:00 PM.", 0.70)]),
    )
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: _CapturingLLM())

    email = type("E", (), {"subject": "Hours?", "body": "What are your opening hours?"})()
    draft, grounded = await email_service._generate_org_grounded_reply(
        db_session, email, front_desk_user
    )

    assert "8:30 AM to 6:00 PM" in captured_prompt["text"]
    assert draft == "Our hours are Mon-Fri 8:30-6:00."
    assert grounded is True


@pytest.mark.asyncio
async def test_org_grounded_reply_falls_back_when_retrieval_insufficient(
    db_session, front_desk_user, monkeypatch
):
    """Below sufficiency_floor: no context is injected, so the model is never
    handed a low-confidence chunk to (mis)represent as fact."""
    captured_prompt = {}

    class _CapturingLLM:
        async def ainvoke(self, prompt: str) -> str:
            captured_prompt["text"] = prompt
            return "Thank you for your email, we'll be in touch."

    monkeypatch.setattr(
        "app.rag.retrieval.retrieve",
        AsyncMock(return_value=[_org_chunk("unrelated low-relevance content", 0.10)]),
    )
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: _CapturingLLM())

    email = type("E", (), {"subject": "Random", "body": "Do you sell parking permits?"})()
    draft, grounded = await email_service._generate_org_grounded_reply(
        db_session, email, front_desk_user
    )

    assert "CLINIC INFO" not in captured_prompt["text"]
    assert draft == "Thank you for your email, we'll be in touch."
    assert grounded is False


@pytest.mark.asyncio
async def test_not_worthy_sender_gets_no_draft_and_is_deprioritized(
    db_session, front_desk_user, monkeypatch
):
    """A newsletter-style sender must never draw a draft, and its reason
    must be visible on the task (handover_context), not silently dropped."""
    from app.models.task import TaskPriority

    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.99})),
    )
    payload = EmailIngestRequest(
        sender="noreply@newsletter.example",
        recipient="clinic@example.com",
        subject="This week's deals",
        body="Check out our latest offers.",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.draft_text is None
    assert outcome.sent is False
    assert outcome.approval_id is None
    assert task.priority == TaskPriority.LOW
    assert task.handover_context is not None
    assert "automated sender" in task.handover_context


@pytest.mark.asyncio
async def test_uncertain_worthiness_still_drafts_but_never_auto_sends(
    db_session, front_desk_user, monkeypatch
):
    """Fail-safe: an undecidable message still gets a draft (so a human can
    act on it), but confidence alone can never push it straight out the
    door."""
    from app.services.reply_gate import ReplyGateResult, ReplyWorthiness

    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.99})),
    )
    monkeypatch.setattr(
        "app.services.email_service.evaluate_reply_worthiness",
        AsyncMock(
            return_value=ReplyGateResult(verdict=ReplyWorthiness.UNCERTAIN, reason="unclear")
        ),
    )
    monkeypatch.setattr(
        "app.services.email_service._generate_org_grounded_reply",
        AsyncMock(return_value=("We'll get back to you.", True)),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Booking",
        body="Please book me in.",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.draft_text == "We'll get back to you."
    assert outcome.sent is False
    assert outcome.approval_id is not None


@pytest.mark.asyncio
async def test_ungrounded_draft_never_auto_sends_even_at_high_confidence(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.99})),
    )
    monkeypatch.setattr(
        "app.services.email_service._generate_org_grounded_reply",
        AsyncMock(return_value=("A generic acknowledgement.", False)),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Booking",
        body="Please book me in for next Tuesday.",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.sent is False
    assert outcome.approval_id is not None


@pytest.mark.asyncio
async def test_clinical_category_never_auto_sends_even_when_worthy_and_grounded(
    db_session, front_desk_user, patient, monkeypatch
):
    """Amin's explicit call: prescription/results/referral replies never
    auto-send regardless of confidence, worthiness, or grounding."""
    from app.models.case import IntakeCase, IntakeStatus

    case = IntakeCase(
        contact_reason="Results",
        contact_channel="email",
        status=IntakeStatus.RECEIVED,
        patient_id=patient.id,
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "results_enquiry", "confidence": 0.99})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="My results",
        body="Can you tell me my blood test results?",
        case_id=case.id,
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.rag.answer.answer_question",
        AsyncMock(return_value=SimpleNamespace(answer="Your results are normal.")),
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.draft_text == "Your results are normal."
    assert outcome.sent is False
    assert outcome.approval_id is not None
