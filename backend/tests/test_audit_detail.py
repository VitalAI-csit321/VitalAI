from uuid import uuid4

from httpx import AsyncClient

from app.models import Patient


async def test_get_audit_event_requires_read_audit_permission(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    listing = await client.get("/api/v1/audit", headers=admin_headers)
    event_id = listing.json()["items"][0]["id"]

    response = await client.get(f"/api/v1/audit/{event_id}", headers=front_desk_headers)
    assert response.status_code == 403


async def test_get_audit_event_returns_real_event(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    listing = await client.get("/api/v1/audit?action=intake.created", headers=admin_headers)
    event_id = listing.json()["items"][0]["id"]

    response = await client.get(f"/api/v1/audit/{event_id}", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == event_id
    assert body["action"] == "intake.created"
    assert body["event_hash"] is not None


async def test_get_audit_event_not_found(client: AsyncClient, admin_headers: dict):
    response = await client.get(f"/api/v1/audit/{uuid4()}", headers=admin_headers)
    assert response.status_code == 404


async def test_getting_audit_event_is_not_itself_logged(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    listing = await client.get("/api/v1/audit?action=intake.created", headers=admin_headers)
    event_id = listing.json()["items"][0]["id"]

    await client.get(f"/api/v1/audit/{event_id}", headers=admin_headers)

    response = await client.get("/api/v1/audit", headers=admin_headers)
    actions = [item["action"] for item in response.json()["items"]]
    assert "audit.event_read" not in actions
