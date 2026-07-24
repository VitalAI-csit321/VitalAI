import uuid

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
    return response.json()["id"]


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


async def test_list_tasks_allowed_for_front_desk(client: AsyncClient, front_desk_headers: dict):
    response = await client.get("/api/v1/tasks", headers=front_desk_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_tasks_denied_for_doctor(client: AsyncClient, doctor_headers: dict):
    response = await client.get("/api/v1/tasks", headers=doctor_headers)
    assert response.status_code == 403
