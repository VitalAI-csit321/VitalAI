import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password
from app.models import IntakeCase, User, UserRole


async def test_create_task_creates_independent_case_and_task(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    response = await client.post(
        "/api/v1/human-review",
        json={
            "task_type": "routing_review",
            "priority": "high",
            "contact_reason": "Manually logged case",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["task_type"] == "routing_review"
    assert body["priority"] == "high"
    assert body["status"] == "pending"
    assert body["target_role"] == "admin"
    assert body["assigned_to"] is None

    case = await db_session.get(IntakeCase, uuid.UUID(body["case_id"]))
    assert case is not None
    assert case.patient_id is None
    assert case.contact_reason == "Manually logged case"


async def test_create_task_defaults_priority_to_medium(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/human-review",
        json={"task_type": "consent_review", "contact_reason": "Manually logged case"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["priority"] == "medium"


async def test_create_task_reviewed_true_sets_completed_status(
    client: AsyncClient, admin_headers: dict
):
    response = await client.post(
        "/api/v1/human-review",
        json={
            "task_type": "consent_review",
            "contact_reason": "Back-logged, already handled",
            "reviewed": True,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "completed"


async def test_create_task_with_owner_sets_assigned_to(
    client: AsyncClient, admin_headers: dict, admin_user: User
):
    response = await client.post(
        "/api/v1/human-review",
        json={
            "task_type": "escalation_review",
            "contact_reason": "Manually logged case",
            "assigned_to": str(admin_user.id),
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["assigned_to"] == str(admin_user.id)


async def test_created_task_appears_in_creators_queue(client: AsyncClient, admin_headers: dict):
    create = await client.post(
        "/api/v1/human-review",
        json={"task_type": "routing_review", "contact_reason": "Manually logged case"},
        headers=admin_headers,
    )
    task_id = create.json()["id"]

    listing = await client.get(
        "/api/v1/human-review?status=pending&limit=100", headers=admin_headers
    )
    ids = [item["id"] for item in listing.json()["items"]]
    assert task_id in ids


async def test_create_task_requires_contact_reason(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/human-review",
        json={"task_type": "routing_review", "contact_reason": ""},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_queue_shows_reason_creator_and_owner_name(
    client: AsyncClient, admin_headers: dict, admin_user: User
):
    await client.post(
        "/api/v1/human-review",
        json={
            "task_type": "escalation_review",
            "contact_reason": "Needs to renew the medicare",
            "assigned_to": str(admin_user.id),
        },
        headers=admin_headers,
    )

    item = (await client.get("/api/v1/human-review", headers=admin_headers)).json()["items"][0]

    assert item["contact_reason"] == "Needs to renew the medicare"
    assert item["created_by"] == "Admin Tester"
    assert item["assigned_to_name"] == "Admin Tester"


async def test_doctor_sees_and_can_claim_own_manual_case(client: AsyncClient, doctor_headers: dict):
    create = await client.post(
        "/api/v1/human-review",
        json={"task_type": "escalation_review", "contact_reason": "Doctor logged case"},
        headers=doctor_headers,
    )
    task_id = create.json()["id"]

    items = (await client.get("/api/v1/human-review", headers=doctor_headers)).json()["items"]
    assert [i["id"] for i in items] == [task_id]
    assert items[0]["created_by"] == "Doctor Tester"

    claim = await client.post(f"/api/v1/human-review/{task_id}/claim", headers=doctor_headers)
    assert claim.status_code == 200


async def test_other_doctor_cannot_see_or_claim_a_doctors_manual_case(
    client: AsyncClient, doctor_headers: dict, db_session: AsyncSession
):
    create = await client.post(
        "/api/v1/human-review",
        json={"task_type": "escalation_review", "contact_reason": "Doctor logged case"},
        headers=doctor_headers,
    )
    task_id = create.json()["id"]
    other = User(
        email="other-doctor@example.com",
        hashed_password=hash_password("password123"),
        full_name="Other Doctor",
        role=UserRole.DOCTOR,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_headers = {"Authorization": f"Bearer {create_access_token(other.id, other.role)}"}

    listing = await client.get("/api/v1/human-review", headers=other_headers)
    assert listing.json()["items"] == []
    claim = await client.post(f"/api/v1/human-review/{task_id}/claim", headers=other_headers)
    assert claim.status_code == 403
