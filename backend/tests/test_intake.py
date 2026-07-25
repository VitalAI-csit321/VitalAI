import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password
from app.models import Patient, User, UserRole


async def test_create_intake(client: AsyncClient, admin_headers: dict, patient: Patient):
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Booking appointment",
            "contact_channel": "phone",
            "notes": "Prefers morning slot",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "intake_received"
    assert body["patient_id"] == str(patient.id)
    assert "id" in body


async def test_get_intake(client: AsyncClient, admin_headers: dict, patient: Patient):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Test result enquiry",
            "contact_channel": "email",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.get(f"/api/v1/intake/{case_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["id"] == case_id


async def test_status_update_blocked_for_front_desk(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict, patient: Patient
):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "y",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.patch(
        f"/api/v1/intake/{case_id}/status",
        json={"status": "consent_pending"},
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_status_update_allowed_for_admin(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "y",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.patch(
        f"/api/v1/intake/{case_id}/status",
        json={"status": "consent_pending"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "consent_pending"


# ---------------------------------------------------------------------------
# RBAC coverage — intake status update
# ---------------------------------------------------------------------------


async def test_status_update_allowed_for_operator(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession, patient: Patient
):
    """operator must be permitted to update intake status."""
    user = User(
        email="operator@intake-rbac.example.com",
        hashed_password=hash_password("pass1234"),
        full_name="Operator",
        role=UserRole.OPERATOR,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    ops_headers = {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}

    create = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.patch(
        f"/api/v1/intake/{case_id}/status",
        json={"status": "consent_pending"},
        headers=ops_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "consent_pending"


async def test_intake_create_allowed_for_front_desk(
    client: AsyncClient, front_desk_headers: dict, patient: Patient
):
    """front_desk must be permitted to create intake cases."""
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "inquiry",
            "contact_channel": "phone",
        },
        headers=front_desk_headers,
    )
    assert response.status_code == 201
    assert response.json()["patient_id"] == str(patient.id)


async def test_intake_create_requires_auth(client: AsyncClient, patient: Patient):
    """Unauthenticated requests must be rejected."""
    response = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
    )
    assert response.status_code == 401


async def test_status_update_not_found_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.patch(
        f"/api/v1/intake/{uuid.uuid4()}/status",
        json={"status": "consent_pending"},
        headers=admin_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_status_update_denied_for_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, patient: Patient
):
    """DOCTOR lacks MANAGE_CASES, must be denied."""
    create = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.patch(
        f"/api/v1/intake/{case_id}/status",
        json={"status": "consent_pending"},
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_intake_create_rejects_nonexistent_patient(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(uuid.uuid4()),
            "contact_reason": "y",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_intake_create_denied_for_doctor(
    client: AsyncClient, doctor_headers: dict, patient: Patient
):
    """DOCTOR lacks VIEW_QUEUE, must be denied creating intake cases."""
    response = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_get_intake_denied_for_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, patient: Patient
):
    """DOCTOR lacks VIEW_QUEUE, must be denied reading intake cases."""
    create = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.get(f"/api/v1/intake/{case_id}", headers=doctor_headers)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /intake — list
# ---------------------------------------------------------------------------


async def test_list_intake_returns_paginated_envelope(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/intake", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["total"] >= 1
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_list_intake_filters_by_channel(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=admin_headers,
    )
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "email"},
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/intake", params={"channel": "email"}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["contact_channel"] == "email" for item in body["items"])


async def test_list_intake_filters_by_status(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    create = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "y", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]
    await client.patch(
        f"/api/v1/intake/{case_id}/status",
        json={"status": "consent_pending"},
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/intake", params={"status": ["consent_pending"]}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item["id"] == case_id for item in body["items"])
    assert all(item["status"] == "consent_pending" for item in body["items"])


async def test_list_intake_search_matches_contact_reason(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "unique-search-term-xyz",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/intake", params={"search": "unique-search-term-xyz"}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["contact_reason"] == "unique-search-term-xyz"


async def test_list_intake_pagination(client: AsyncClient, admin_headers: dict, patient: Patient):
    for _ in range(3):
        await client.post(
            "/api/v1/intake",
            json={
                "patient_id": str(patient.id),
                "contact_reason": "pagination-case",
                "contact_channel": "phone",
            },
            headers=admin_headers,
        )

    response = await client.get(
        "/api/v1/intake",
        params={"search": "pagination-case", "limit": 2, "offset": 0},
        headers=admin_headers,
    )
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


async def test_list_intake_denied_without_view_queue(client: AsyncClient, doctor_headers: dict):
    """DOCTOR lacks VIEW_QUEUE, must be denied listing intake cases."""
    response = await client.get("/api/v1/intake", headers=doctor_headers)
    assert response.status_code == 403


async def test_list_intake_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/intake")
    assert response.status_code == 401
