import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import approval_service


async def _pending_approval(db_session: AsyncSession):
    return await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )


async def test_list_approvals_allowed_for_operator(
    client: AsyncClient, operator_headers: dict, db_session: AsyncSession
):
    await _pending_approval(db_session)

    response = await client.get("/api/v1/approvals", headers=operator_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "pending"


async def test_list_approvals_denied_for_front_desk(client: AsyncClient, front_desk_headers: dict):
    response = await client.get("/api/v1/approvals", headers=front_desk_headers)
    assert response.status_code == 403


async def test_list_approvals_denied_for_doctor(client: AsyncClient, doctor_headers: dict):
    response = await client.get("/api/v1/approvals", headers=doctor_headers)
    assert response.status_code == 403


async def test_approve_allowed_for_admin(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)

    response = await client.post(
        f"/api/v1/approvals/{request.id}/approve",
        json={"notes": "looks good"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["decision_notes"] == "looks good"


async def test_approve_with_resolved_payload(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)

    response = await client.post(
        f"/api/v1/approvals/{request.id}/approve",
        json={"resolved_payload": {"draft": "edited"}},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["resolved_payload"] == {"draft": "edited"}


async def test_reject_allowed_for_operator(
    client: AsyncClient, operator_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)

    response = await client.post(
        f"/api/v1/approvals/{request.id}/reject",
        json={"notes": "not accurate"},
        headers=operator_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["decision_notes"] == "not accurate"


async def test_approve_denied_for_front_desk(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)

    response = await client.post(
        f"/api/v1/approvals/{request.id}/approve", json={}, headers=front_desk_headers
    )

    assert response.status_code == 403


async def test_approve_denied_for_doctor(
    client: AsyncClient, doctor_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)

    response = await client.post(
        f"/api/v1/approvals/{request.id}/approve", json={}, headers=doctor_headers
    )

    assert response.status_code == 403


async def test_reject_denied_for_front_desk(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)

    response = await client.post(
        f"/api/v1/approvals/{request.id}/reject", json={}, headers=front_desk_headers
    )

    assert response.status_code == 403


async def test_approve_missing_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        f"/api/v1/approvals/{uuid.uuid4()}/approve", json={}, headers=admin_headers
    )
    assert response.status_code == 404


async def test_reject_missing_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        f"/api/v1/approvals/{uuid.uuid4()}/reject", json={}, headers=admin_headers
    )
    assert response.status_code == 404


async def test_approve_already_decided_returns_409(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)
    first = await client.post(
        f"/api/v1/approvals/{request.id}/approve", json={}, headers=admin_headers
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/approvals/{request.id}/approve", json={}, headers=admin_headers
    )
    assert second.status_code == 409


async def test_reject_already_decided_returns_409(
    client: AsyncClient, admin_headers: dict, db_session: AsyncSession
):
    request = await _pending_approval(db_session)
    first = await client.post(
        f"/api/v1/approvals/{request.id}/reject", json={}, headers=admin_headers
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/approvals/{request.id}/reject", json={}, headers=admin_headers
    )
    assert second.status_code == 409
