import json
from unittest.mock import AsyncMock, patch

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


async def test_override_task_category_updates_target_role_and_audits(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("We're open 9-5.", True)),
    ):
        ingest = await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Question",
                "body": "What are your hours?",
            },
            headers=admin_headers,
        )
    assert ingest.status_code == 201
    task_id = ingest.json()["task_id"]

    override = await client.post(
        f"/api/v1/tasks/{task_id}/override",
        json={"category": "referral_request", "reason": "Actually a referral, misclassified"},
        headers=admin_headers,
    )

    assert override.status_code == 200
    body = override.json()
    assert body["category"] == "referral_request"
    assert body["target_role"] == "operator"

    audit_case_id = ingest.json()["email"]["case_id"]
    audit = await client.get(f"/api/v1/audit/by-case/{audit_case_id}", headers=admin_headers)
    actions = [event["action"] for event in audit.json()]
    assert "task.override_recorded" in actions


async def test_override_task_requires_manage_cases(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("We're open 9-5.", True)),
    ):
        ingest = await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Question",
                "body": "What are your hours?",
            },
            headers=front_desk_headers,
        )
    task_id = ingest.json()["task_id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/override",
        json={"category": "referral_request", "reason": "test"},
        headers=front_desk_headers,
    )
    assert response.status_code == 403
