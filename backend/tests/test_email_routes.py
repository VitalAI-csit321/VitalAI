import json
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
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
        new=AsyncMock(return_value="Thanks, we'll confirm your appointment shortly."),
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
    assert body["sent"] is True
    assert body["draft_text"] == "Thanks, we'll confirm your appointment shortly."


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
