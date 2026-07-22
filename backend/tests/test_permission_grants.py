from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token
from app.models import User
from app.models.audit import AuditEvent


async def test_admin_can_grant_read_audit_to_operator(
    client: AsyncClient, admin_headers: dict, operator_user: User
):
    response = await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["permission"] == "read_audit"
    assert response.json()["user_id"] == str(operator_user.id)


async def test_grant_not_grantable_to_role_returns_422(
    client: AsyncClient, admin_headers: dict, front_desk_user: User
):
    """FRONT_DESK has no GRANTABLE entry, so any grant attempt must be rejected."""
    response = await client.post(
        f"/api/v1/auth/users/{front_desk_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_duplicate_grant_returns_409(
    client: AsyncClient, admin_headers: dict, operator_user: User
):
    first = await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )
    assert second.status_code == 409


async def test_operator_cannot_grant_permissions(
    client: AsyncClient, operator_headers: dict, operator_user: User
):
    """OPERATOR lacks MANAGE_USERS, must be denied granting to anyone, including themselves."""
    response = await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=operator_headers,
    )
    assert response.status_code == 403


async def test_grant_then_operator_can_read_audit(
    client: AsyncClient, admin_headers: dict, operator_user: User, db_session: AsyncSession
):
    """End-to-end: grant READ_AUDIT to an operator, then prove GET /audit/by-case works."""
    await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )
    target_headers = {
        "Authorization": f"Bearer {create_access_token(operator_user.id, operator_user.role)}"
    }

    create = await client.post(
        "/api/v1/intake",
        json={"patient_name": "Grant Test", "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    db_session.expire_all()
    response = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=target_headers)
    assert response.status_code == 200


async def test_revoke_grant(
    client: AsyncClient, admin_headers: dict, operator_user: User, db_session: AsyncSession
):
    await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )

    response = await client.delete(
        f"/api/v1/auth/users/{operator_user.id}/grants/read_audit", headers=admin_headers
    )
    assert response.status_code == 204

    target_headers = {
        "Authorization": f"Bearer {create_access_token(operator_user.id, operator_user.role)}"
    }
    create = await client.post(
        "/api/v1/intake",
        json={"patient_name": "Revoke Test", "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]
    db_session.expire_all()
    audit_response = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=target_headers)
    assert audit_response.status_code == 403


async def test_revoke_nonexistent_grant_returns_404(
    client: AsyncClient, admin_headers: dict, operator_user: User
):
    response = await client.delete(
        f"/api/v1/auth/users/{operator_user.id}/grants/read_audit", headers=admin_headers
    )
    assert response.status_code == 404


async def test_grant_written_to_audit_log(
    client: AsyncClient, admin_headers: dict, operator_user: User, db_session: AsyncSession
):
    await client.post(
        f"/api/v1/auth/users/{operator_user.id}/grants",
        json={"permission": "read_audit"},
        headers=admin_headers,
    )

    # Grants are actor-only events (no case_id), so query directly rather than
    # via GET /audit/by-case, which only returns events tied to a specific case.
    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "user.permission_granted")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].details["target_user_id"] == str(operator_user.id)
    assert events[0].details["permission"] == "read_audit"
