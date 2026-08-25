import json
from typing import cast
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


def _mock_classifier(monkeypatch, category: str, confidence: float) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": category, "confidence": confidence})),
    )


async def _ingest(client: AsyncClient, headers: dict) -> dict:
    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("Reply body.", True)),
    ):
        response = await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Question",
                "body": "What are your hours?",
            },
            headers=headers,
        )
    assert response.status_code == 201
    return cast(dict, response.json())


async def test_escalate_task_sets_urgent_and_escalated(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/escalate",
        json={"reason": "Needs a human"},
        headers=front_desk_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "escalated"
    assert body["priority"] == "urgent"


async def test_escalate_task_twice_returns_409(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    await client.post(f"/api/v1/tasks/{task_id}/escalate", json={}, headers=front_desk_headers)
    second = await client.post(
        f"/api/v1/tasks/{task_id}/escalate", json={}, headers=front_desk_headers
    )

    assert second.status_code == 409


async def test_archive_task_removes_it_from_inbox(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    archive = await client.post(f"/api/v1/tasks/{task_id}/archive", headers=front_desk_headers)
    assert archive.status_code == 200
    assert archive.json()["status"] == "completed"

    inbox = await client.get("/api/v1/inbox", headers=front_desk_headers)
    assert not any(m["id"] == task_id for m in inbox.json()["items"])


async def test_escalate_and_archive_require_auth(client: AsyncClient):
    import uuid

    task_id = str(uuid.uuid4())
    escalate = await client.post(f"/api/v1/tasks/{task_id}/escalate", json={})
    archive = await client.post(f"/api/v1/tasks/{task_id}/archive")
    assert escalate.status_code == 401
    assert archive.status_code == 401


async def test_escalate_denied_when_task_targets_a_different_role(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    # prescription_renewal resolves to UserRole.DOCTOR, not front_desk's own role.
    _mock_classifier(monkeypatch, "prescription_renewal", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/escalate", json={}, headers=front_desk_headers
    )

    assert response.status_code == 403


async def test_archive_denied_for_doctor_unassigned_to_the_patient(
    client: AsyncClient, front_desk_headers: dict, doctor_headers: dict, monkeypatch
):
    # prescription_renewal resolves to UserRole.DOCTOR, but this doctor has no
    # assignment to the patient behind the ingested email's case.
    _mock_classifier(monkeypatch, "prescription_renewal", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.post(f"/api/v1/tasks/{task_id}/archive", headers=doctor_headers)

    assert response.status_code == 403


async def test_inbox_surfaces_persisted_draft(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)

    inbox = await client.get("/api/v1/inbox", headers=front_desk_headers)
    item = next(m for m in inbox.json()["items"] if m["id"] == ingest["task_id"])

    assert item["draftText"] == "Reply body."
    assert item["draftSent"] is True
    assert item["taskStatus"] == "pending"


async def test_admin_can_delete_task(client: AsyncClient, admin_headers: dict, monkeypatch):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)

    assert response.status_code == 200


async def test_operator_can_delete_task(
    client: AsyncClient, operator_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, operator_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=operator_headers)

    assert response.status_code == 200


async def test_front_desk_cannot_delete_task(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=front_desk_headers)

    assert response.status_code == 403


async def test_doctor_cannot_delete_task(
    client: AsyncClient, front_desk_headers: dict, doctor_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=doctor_headers)

    assert response.status_code == 403


async def test_deleted_task_is_invisible_in_inbox_and_archived_view(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    delete = await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)
    assert delete.status_code == 200

    inbox = await client.get("/api/v1/inbox", headers=admin_headers)
    archived = await client.get("/api/v1/inbox?archived=true", headers=admin_headers)

    assert not any(m["id"] == task_id for m in inbox.json()["items"])
    assert not any(m["id"] == task_id for m in archived.json()["items"])


async def test_deleted_task_stays_invisible_even_after_archiving(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    """Soft delete must win over archive/completed status in both views."""
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    await client.post(f"/api/v1/tasks/{task_id}/archive", headers=admin_headers)
    await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)

    archived = await client.get("/api/v1/inbox?archived=true", headers=admin_headers)

    assert not any(m["id"] == task_id for m in archived.json()["items"])


async def test_archived_view_returns_only_completed_tasks(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    pending = await _ingest(client, admin_headers)
    to_archive = await _ingest(client, admin_headers)
    await client.post(f"/api/v1/tasks/{to_archive['task_id']}/archive", headers=admin_headers)

    archived = await client.get("/api/v1/inbox?archived=true", headers=admin_headers)
    archived_ids = {m["id"] for m in archived.json()["items"]}

    assert to_archive["task_id"] in archived_ids
    assert pending["task_id"] not in archived_ids


async def test_task_starts_unread_and_flips_after_marking_read(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    before = await client.get("/api/v1/inbox", headers=admin_headers)
    item_before = next(m for m in before.json()["items"] if m["id"] == task_id)
    assert item_before["unread"] is True

    mark_read = await client.post(f"/api/v1/tasks/{task_id}/read", headers=admin_headers)
    assert mark_read.status_code == 200

    after = await client.get("/api/v1/inbox", headers=admin_headers)
    item_after = next(m for m in after.json()["items"] if m["id"] == task_id)
    assert item_after["unread"] is False
