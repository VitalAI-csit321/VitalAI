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
