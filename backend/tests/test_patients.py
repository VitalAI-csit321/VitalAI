from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.user import User


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
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, doctor_user: User
):
    created = await client.post(
        "/api/v1/patients",
        json={"name": "Search Me", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )
    await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": created.json()["id"]},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/patients", headers=doctor_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert set(body["counts"].keys()) == {"active", "pending", "inactive"}


async def test_list_patients_scoped_to_assigned_for_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, doctor_user: User
):
    assigned = await client.post(
        "/api/v1/patients",
        json={"name": "Assigned Patient", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )
    await client.post(
        "/api/v1/patients",
        json={"name": "Unassigned Patient", "dob": "1990-01-01", "gender": "male"},
        headers=admin_headers,
    )
    await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": assigned.json()["id"]},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/patients", headers=doctor_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Assigned Patient"
    assert body["counts"]["pending"] == 1


async def test_list_patients_unscoped_for_admin(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/v1/patients",
        json={"name": "Not Assigned To Anyone", "dob": "1990-01-01", "gender": "male"},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/patients", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1


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


async def test_update_patient_changes_provided_fields_only(
    client: AsyncClient, admin_headers: dict
):
    create_res = await client.post(
        "/api/v1/patients",
        json={"name": "Original Name", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )
    patient_id = create_res.json()["id"]

    update_res = await client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"name": "Updated Name"},
        headers=admin_headers,
    )

    assert update_res.status_code == 200
    body = update_res.json()
    assert body["name"] == "Updated Name"
    assert body["dob"] == "1990-01-01"  # untouched field stays as created


async def test_update_patient_denied_for_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict
):
    create_res = await client.post(
        "/api/v1/patients",
        json={"name": "Doctor Cannot Edit", "dob": "1990-01-01", "gender": "male"},
        headers=admin_headers,
    )
    patient_id = create_res.json()["id"]

    response = await client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"name": "Hacked Name"},
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_update_patient_not_found(client: AsyncClient, admin_headers: dict):
    response = await client.patch(
        "/api/v1/patients/00000000-0000-0000-0000-000000000000",
        json={"name": "Nobody"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_patient_updated_audit_event_is_logged(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    create_res = await client.post(
        "/api/v1/patients",
        json={"name": "Audited Update Patient", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )
    patient_id = create_res.json()["id"]

    await client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"status": "active"},
        headers=admin_headers,
    )

    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "patient.updated")
    )
    events = result.scalars().all()
    assert any(e.details.get("patient_id") == patient_id for e in events)


async def test_get_patient_returns_full_record(client: AsyncClient, admin_headers: dict):
    created = await client.post(
        "/api/v1/patients",
        json={"name": "Detail Fetch", "dob": "1985-05-05", "gender": "male"},
        headers=admin_headers,
    )
    patient_id = created.json()["id"]

    response = await client.get(f"/api/v1/patients/{patient_id}", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == patient_id
    assert body["name"] == "Detail Fetch"


async def test_get_patient_404_for_unknown_id(client: AsyncClient, admin_headers: dict):
    response = await client.get(
        "/api/v1/patients/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404


async def test_get_patient_404_for_doctor_not_assigned(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict
):
    created = await client.post(
        "/api/v1/patients",
        json={"name": "Not My Patient", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )
    patient_id = created.json()["id"]

    response = await client.get(f"/api/v1/patients/{patient_id}", headers=doctor_headers)

    assert response.status_code == 404


async def test_get_patient_200_for_assigned_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, doctor_user: User
):
    created = await client.post(
        "/api/v1/patients",
        json={"name": "My Patient", "dob": "1990-01-01", "gender": "female"},
        headers=admin_headers,
    )
    patient_id = created.json()["id"]
    await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": patient_id},
        headers=admin_headers,
    )

    response = await client.get(f"/api/v1/patients/{patient_id}", headers=doctor_headers)

    assert response.status_code == 200
    assert response.json()["id"] == patient_id
