import uuid
from typing import cast

from httpx import AsyncClient

from app.models import Patient, User


async def _create_case(client: AsyncClient, headers: dict, patient: Patient) -> str:
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Create manual task",
            "contact_channel": "phone",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return cast(str, response.json()["id"])


async def test_create_task_manual_entry(
    client: AsyncClient,
    operator_headers: dict,
    operator_user: User,
    patient: Patient,
):
    case_id = await _create_case(client, operator_headers, patient)

    response = await client.post(
        "/api/v1/tasks",
        json={
            "case_id": case_id,
            "assigned_to": str(operator_user.id),
            "source": "call",
            "priority": "high",
        },
        headers=operator_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["case_id"] == case_id
    assert body["assigned_to"] == str(operator_user.id)
    assert body["source"] == "call"
    assert body["priority"] == "high"
    assert body["status"] == "pending"


async def test_create_task_records_audit_event(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "email"},
        headers=admin_headers,
    )
    assert response.status_code == 201

    audit = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert audit.status_code == 200
    assert "task.created" in [event["action"] for event in audit.json()]


async def test_create_task_denied_for_front_desk(
    client: AsyncClient,
    front_desk_headers: dict,
    patient: Patient,
):
    case_id = await _create_case(client, front_desk_headers, patient)
    response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_create_task_rejects_missing_case(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/tasks",
        json={"case_id": str(uuid.uuid4()), "source": "call"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_create_task_rejects_missing_assignee(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/tasks",
        json={
            "case_id": case_id,
            "assigned_to": str(uuid.uuid4()),
            "source": "call",
        },
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_list_tasks_allowed_for_front_desk(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict, patient: Patient
):
    # list_tasks has no role-based scoping (unlike the newer inbox_service),
    # so it returns every task in the dev/CI Postgres this suite runs
    # against, including real ones from product usage -- asserting an empty
    # list was only ever incidentally true while that table was empty.
    # What this endpoint's permission gate actually promises is that
    # front_desk is authorized to call it and sees its own task in the result.
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks", json={"case_id": case_id, "source": "call"}, headers=admin_headers
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    response = await client.get("/api/v1/tasks", headers=front_desk_headers)
    assert response.status_code == 200
    assert any(t["id"] == task_id for t in response.json())


async def test_list_tasks_denied_for_doctor(client: AsyncClient, doctor_headers: dict):
    response = await client.get("/api/v1/tasks", headers=doctor_headers)
    assert response.status_code == 403


async def test_update_task_status_and_records_audit_event(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "completed"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    audit = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert "task.updated" in [event["action"] for event in audit.json()]


async def test_update_task_reassign(
    client: AsyncClient, admin_headers: dict, operator_user: User, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "email"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"assigned_to": str(operator_user.id)},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(operator_user.id)


async def test_update_task_rejects_missing_assignee(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"assigned_to": str(uuid.uuid4())},
        headers=admin_headers,
    )

    assert response.status_code == 404


async def test_update_task_denied_for_front_desk(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "completed"},
        headers=front_desk_headers,
    )

    assert response.status_code == 403


async def test_update_task_rejects_missing_task(client: AsyncClient, admin_headers: dict):
    response = await client.patch(
        f"/api/v1/tasks/{uuid.uuid4()}",
        json={"status": "completed"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_add_comment_persists_and_lists(
    client: AsyncClient, admin_headers: dict, admin_user: User, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    post_response = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"body": "Called the patient back, awaiting callback."},
        headers=admin_headers,
    )
    assert post_response.status_code == 201
    body = post_response.json()
    assert body["body"] == "Called the patient back, awaiting callback."
    assert body["task_id"] == task_id
    assert body["author_id"] == str(admin_user.id)

    list_response = await client.get(f"/api/v1/tasks/{task_id}/comments", headers=admin_headers)
    assert list_response.status_code == 200
    comments = list_response.json()
    assert len(comments) == 1
    assert comments[0]["body"] == "Called the patient back, awaiting callback."


async def test_add_comment_records_audit_event(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"body": "Note."},
        headers=admin_headers,
    )

    audit = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert "task.commented" in [event["action"] for event in audit.json()]


async def test_add_comment_rejects_missing_task(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        f"/api/v1/tasks/{uuid.uuid4()}/comments",
        json={"body": "Note."},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_add_comment_rejects_empty_body(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "source": "call"},
        headers=admin_headers,
    )
    task_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"body": ""},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_list_tasks_includes_subject_and_from_name_for_email_tasks(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    import json
    from unittest.mock import AsyncMock, patch

    class _FakeLLM:
        def __init__(self, response: str):
            self.response = response

        async def ainvoke(self, prompt: str) -> str:
            if "worthy" in prompt.lower():
                return json.dumps({"worthy": True, "reason": "test default"})
            return self.response

    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("ok", True)),
    ):
        await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Identify me",
                "body": "Some question.",
            },
            headers=front_desk_headers,
        )

    response = await client.get("/api/v1/tasks", headers=front_desk_headers)

    assert response.status_code == 200
    task = next(t for t in response.json() if t["subject"] == "Identify me")
    assert task["from_name"] == "patient@example.com"
