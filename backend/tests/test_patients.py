from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent


async def test_create_patient_allowed_for_front_desk(client: AsyncClient, front_desk_headers: dict):
    response = await client.post(
        "/api/v1/patients",
        json={"name": "Ada Lovelace", "dob": "1990-01-01", "gender": "female"},
        headers=front_desk_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Ada Lovelace"
    assert body["status"] == "pending"
    assert body["mrn"].startswith("MRN-")


async def test_create_patient_denied_for_doctor(client: AsyncClient, doctor_headers: dict):
    response = await client.post(
        "/api/v1/patients",
        json={"name": "X", "dob": "1990-01-01", "gender": "male"},
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_create_patient_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/patients",
        json={"name": "X", "dob": "1990-01-01", "gender": "male"},
    )
    assert response.status_code == 401


async def test_list_patients_allowed_for_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict
):
    await client.post(
        "/api/v1/patients",
        json={"name": "Search Me", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/patients", headers=doctor_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert set(body["counts"].keys()) == {"active", "pending", "inactive"}


async def test_list_patients_denied_without_auth(client: AsyncClient):
    response = await client.get("/api/v1/patients")
    assert response.status_code == 401


async def test_list_patients_search_query_param(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/v1/patients",
        json={"name": "Unique Searchname", "dob": "1990-01-01", "gender": "male"},
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/patients", params={"search": "searchname"}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Unique Searchname"


async def test_patient_registered_audit_event_is_logged(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    response = await client.post(
        "/api/v1/patients",
        json={"name": "Audited Patient", "dob": "1990-01-01", "gender": "non_binary"},
        headers=admin_headers,
    )
    patient_id = response.json()["id"]

    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "patient.registered")
    )
    events = result.scalars().all()
    assert any(e.details.get("patient_id") == patient_id for e in events)
