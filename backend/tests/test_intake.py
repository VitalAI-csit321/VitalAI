import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password
from app.models import User, UserRole


async def test_create_intake(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "Jane Synthetic",
            "contact_reason": "Booking appointment",
            "contact_channel": "phone",
            "notes": "Prefers morning slot",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "intake_received"
    assert body["patient_name"] == "Jane Synthetic"
    assert "id" in body


async def test_get_intake(client: AsyncClient, admin_headers: dict):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "John Synthetic",
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
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "x",
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


async def test_status_update_allowed_for_admin(client: AsyncClient, admin_headers: dict):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "x",
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


async def test_status_update_allowed_for_ops_manager(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    """ops_manager must be permitted to update intake status."""
    user = User(
        email="opsmgr@intake-rbac.example.com",
        hashed_password=hash_password("pass1234"),
        full_name="Ops Manager",
        role=UserRole.OPS_MANAGER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    ops_headers = {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}

    create = await client.post(
        "/api/v1/intake",
        json={"patient_name": "x", "contact_reason": "y", "contact_channel": "phone"},
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
    client: AsyncClient, front_desk_headers: dict
):
    """front_desk must be permitted to create intake cases."""
    response = await client.post(
        "/api/v1/intake",
        json={"patient_name": "FD Patient", "contact_reason": "inquiry", "contact_channel": "phone"},
        headers=front_desk_headers,
    )
    assert response.status_code == 201
    assert response.json()["patient_name"] == "FD Patient"


async def test_intake_create_requires_auth(client: AsyncClient):
    """Unauthenticated requests must be rejected."""
    response = await client.post(
        "/api/v1/intake",
        json={"patient_name": "x", "contact_reason": "y", "contact_channel": "phone"},
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
