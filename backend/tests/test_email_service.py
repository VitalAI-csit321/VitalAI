import json
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.email import EmailIngestRequest
from app.services import email_service


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
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
        new=AsyncMock(return_value="We open at 9am on Saturdays."),
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
        new=AsyncMock(return_value="Your prescription is ready for pickup."),
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
    draft = await email_service._generate_org_grounded_reply(db_session, email, front_desk_user)

    assert "8:30 AM to 6:00 PM" in captured_prompt["text"]
    assert draft == "Our hours are Mon-Fri 8:30-6:00."


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
    draft = await email_service._generate_org_grounded_reply(db_session, email, front_desk_user)

    assert "CLINIC INFO" not in captured_prompt["text"]
    assert draft == "Thank you for your email, we'll be in touch."
