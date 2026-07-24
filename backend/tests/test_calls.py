import uuid

from httpx import AsyncClient

from app.models import Patient


async def _create_case(client: AsyncClient, headers: dict, patient: Patient) -> str:
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Manual call intake",
            "contact_channel": "phone",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_create_call_manual_entry(
    client: AsyncClient, front_desk_headers: dict, patient: Patient
):
    case_id = await _create_case(client, front_desk_headers, patient)

    response = await client.post(
        "/api/v1/calls",
        json={
            "case_id": case_id,
            "phone_number": "0412345678",
            "transcript": "Caller requested an appointment change.",
        },
        headers=front_desk_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["case_id"] == case_id
    assert body["phone_number"] == "0412345678"
    assert body["transcript"] == "Caller requested an appointment change."
    assert body["status"] == "received"


async def test_create_call_records_audit_event(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/calls",
        json={"case_id": case_id, "phone_number": "0399999999", "transcript": "Test"},
        headers=admin_headers,
    )
    assert response.status_code == 201

    audit = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert audit.status_code == 200
    assert "call.created" in [event["action"] for event in audit.json()]


async def test_create_call_rejects_missing_case(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/calls",
        json={"case_id": str(uuid.uuid4()), "phone_number": "0412345678"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_list_calls_requires_view_queue(client: AsyncClient, doctor_headers: dict):
    response = await client.get("/api/v1/calls", headers=doctor_headers)
    assert response.status_code == 403


async def test_create_call_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/calls",
        json={"case_id": str(uuid.uuid4()), "phone_number": "0412345678"},
    )
    assert response.status_code == 401
