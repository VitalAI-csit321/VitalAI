import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class _FakeLLM:
    """Answers the classifier's canned response, and answers WORTHY to the
    reply-worthiness gate's separate call -- these tests aren't exercising
    that gate (see test_reply_gate.py), they just need it out of the way.
    """

    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


def _mock_classifier(monkeypatch, category: str, confidence: float) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": category, "confidence": confidence})),
    )


async def test_ingest_email_endpoint_creates_task(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "appointment_request", 0.95)

    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("Thanks, we'll confirm your appointment shortly.", True)),
    ):
        response = await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Need an appointment",
                "body": "Can I book an appointment for next week?",
            },
            headers=front_desk_headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["email"]["subject"] == "Need an appointment"
    assert body["category"] == "appointment_request"
    assert body["outcome"] == "auto_routed"
    assert body["confidence"] == 0.95
    # The draft is no longer in the response: it is generated after it, and
    # lands on the Task row. See tests/test_draft_reply_detached.py.
    assert "draft_text" not in body


async def test_ingest_email_requires_view_queue(
    client: AsyncClient, doctor_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "appointment_request", 0.95)

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Need an appointment",
            "body": "Can I book an appointment for next week?",
        },
        headers=doctor_headers,
    )

    assert response.status_code == 403


async def test_ingest_email_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Need an appointment",
            "body": "Can I book an appointment for next week?",
        },
    )
    assert response.status_code == 401


async def test_ingesting_the_same_external_message_twice_is_a_conflict_not_a_500(
    client: AsyncClient, front_desk_headers: dict, monkeypatch, db_session
):
    if db_session.bind.dialect.name == "sqlite":
        # The unique index is migration 0024's, not the model's, and the SQLite
        # track builds its schema from the models. Postgres, which CI runs, is
        # the real check.
        pytest.skip("the dedupe index only exists after alembic")
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    payload = {
        "sender": "patient@example.com",
        "recipient": "clinic@example.com",
        "subject": "Hours",
        "body": "When are you open?",
        "external_id": "AAMk-duplicate",
        "external_source": "outlook",
    }

    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("We open at 8:30.", True)),
    ):
        first = await client.post("/api/v1/email/ingest", json=payload, headers=front_desk_headers)
        second = await client.post("/api/v1/email/ingest", json=payload, headers=front_desk_headers)

    assert first.status_code == 201
    assert second.status_code == 409


async def test_an_intent_check_review_puts_its_reason_on_the_task(
    client: AsyncClient, front_desk_headers: dict, monkeypatch, db_session
):
    from uuid import UUID

    from app.models.task import Task

    _mock_classifier(monkeypatch, "appointment_request", 0.95)
    monkeypatch.setattr("app.config.settings.intent_check_enabled", True)

    async def disagree(text: str) -> tuple[str, float]:
        return "general_administrative", 0.3

    monkeypatch.setattr("app.services.content_classifier.regression_view", disagree)

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Hi",
            "body": "The second one please.",
        },
        headers=front_desk_headers,
    )

    assert response.json()["outcome"] == "human_review"
    task = await db_session.get(Task, UUID(response.json()["task_id"]))
    await db_session.refresh(task)
    assert "second opinion: general_administrative" in task.handover_context
