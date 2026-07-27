import json

from httpx import AsyncClient


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        return self.response


def _mock_email_classifier(monkeypatch, category: str, confidence: float) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": category, "confidence": confidence})),
    )


async def test_inbox_filters_by_target_role(
    client: AsyncClient, operator_headers: dict, front_desk_headers: dict, monkeypatch
):
    from unittest.mock import AsyncMock, patch

    _mock_email_classifier(monkeypatch, "referral_request", 0.95)  # -> operator
    with patch(
        "app.services.email_service._generate_plain_reply", new=AsyncMock(return_value="ok")
    ):
        await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Referral needed",
                "body": "I need a referral to a specialist.",
            },
            headers=operator_headers,
        )

    operator_inbox = await client.get("/api/v1/inbox", headers=operator_headers)
    front_desk_inbox = await client.get("/api/v1/inbox", headers=front_desk_headers)

    assert operator_inbox.status_code == 200
    assert any(m["subject"] == "Referral needed" for m in operator_inbox.json()["items"])
    assert not any(m["subject"] == "Referral needed" for m in front_desk_inbox.json()["items"])


async def test_inbox_message_shape_matches_frontend_contract(
    client: AsyncClient, operator_headers: dict, monkeypatch
):
    from unittest.mock import AsyncMock, patch

    _mock_email_classifier(monkeypatch, "medical_records_request", 0.95)  # -> operator
    with patch(
        "app.services.email_service._generate_plain_reply", new=AsyncMock(return_value="ok")
    ):
        await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "jane@example.com",
                "recipient": "clinic@example.com",
                "subject": "Records request",
                "body": "Please send my medical records.",
            },
            headers=operator_headers,
        )

    response = await client.get("/api/v1/inbox", headers=operator_headers)

    assert response.status_code == 200
    item = next(m for m in response.json()["items"] if m["subject"] == "Records request")
    for field in (
        "id",
        "fromName",
        "fromInitials",
        "toName",
        "subject",
        "body",
        "priority",
        "category",
        "unread",
        "receivedLabel",
        "threadReference",
        "avatarColor",
    ):
        assert field in item
    assert item["category"] == "medical_records_request"
    assert item["priority"] in ("urgent", "normal", "fyi")


async def test_inbox_requires_view_queue_or_view_clinical(client: AsyncClient, admin_headers: dict):
    response = await client.get("/api/v1/inbox", headers=admin_headers)
    assert response.status_code == 200


async def test_inbox_summarizes_call_transcripts(
    client: AsyncClient, operator_headers: dict, patient, monkeypatch
):
    from unittest.mock import AsyncMock, patch

    monkeypatch.setattr(
        "app.services.call_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "referral_request", "confidence": 0.95})),
    )
    case = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "call",
            "contact_channel": "phone",
        },
        headers=operator_headers,
    )
    case_id = case.json()["id"]
    consent_created = await client.post(
        "/api/v1/consent",
        json={"case_id": case_id, "consent_type": "administrative"},
        headers=operator_headers,
    )
    await client.post(
        f"/api/v1/consent/{consent_created.json()['id']}/capture", headers=operator_headers
    )
    call = await client.post(
        "/api/v1/calls",
        json={
            "case_id": case_id,
            "phone_number": "0412345678",
            "transcript": "Caller wants to reschedule Tuesday's appointment to Thursday.",
        },
        headers=operator_headers,
    )
    await client.post(f"/api/v1/calls/{call.json()['id']}/route", json={}, headers=operator_headers)

    with patch(
        "app.services.inbox_service.summarize_call",
        new=AsyncMock(
            return_value="Caller requests rescheduling Tuesday's appointment to Thursday."
        ),
    ):
        response = await client.get("/api/v1/inbox", headers=operator_headers)

    assert response.status_code == 200
    item = next(m for m in response.json()["items"] if m["threadReference"].startswith("CALL-"))
    assert item["body"] == "Caller requests rescheduling Tuesday's appointment to Thursday."
