import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IntakeCase, User


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


async def test_create_task_defaults_priority_to_medium(
    client: AsyncClient, admin_headers: dict
):
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


async def test_created_task_appears_in_creators_queue(
    client: AsyncClient, admin_headers: dict
):
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
