from httpx import AsyncClient
from sqlalchemy import select

from app.models import Patient, User
from app.models.audit import AuditEvent


async def test_register_then_login(client: AsyncClient, admin_headers: dict):
    register_response = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "newuser@example.com",
            "password": "password123",
            "full_name": "New User",
            "role": "front_desk",
        },
    )
    assert register_response.status_code == 201
    assert register_response.json()["email"] == "newuser@example.com"

    login_response = await client.post(
        "/api/v1/auth/login",
        data={"username": "newuser@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    assert token

    me_response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "newuser@example.com"


async def test_login_wrong_password(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "user@example.com",
            "password": "password123",
            "full_name": "User",
            "role": "front_desk",
        },
    )
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "user@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


async def test_register_duplicate_email(client: AsyncClient, admin_headers: dict):
    payload = {
        "email": "dupe@example.com",
        "password": "password123",
        "full_name": "Dupe",
        "role": "front_desk",
    }
    first = await client.post("/api/v1/auth/register", json=payload, headers=admin_headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload, headers=admin_headers)
    assert second.status_code == 409


async def test_protected_endpoint_requires_token(client: AsyncClient, patient: Patient):
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "y",
            "contact_channel": "phone",
        },
    )
    assert response.status_code == 401


async def test_register_ignores_role_in_payload(client: AsyncClient, admin_headers: dict):
    """Sending role=admin in the register payload must still result in front_desk."""
    response = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "tryingadmin@example.com",
            "password": "password123",
            "full_name": "Role Abuser",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "front_desk"


async def test_admin_can_elevate_user_role(client: AsyncClient, admin_headers: dict):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "target@example.com",
            "password": "password123",
            "full_name": "Target User",
        },
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    assert reg.json()["role"] == "front_desk"

    elevate = await client.post(
        f"/api/v1/auth/users/{user_id}/elevate",
        json={"new_role": "operator"},
        headers=admin_headers,
    )
    assert elevate.status_code == 200
    assert elevate.json()["role"] == "operator"


async def test_front_desk_cannot_elevate_role(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "another@example.com",
            "password": "password123",
            "full_name": "Another User",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/elevate",
        json={"new_role": "admin"},
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_operator_cannot_elevate_role(
    client: AsyncClient, admin_headers: dict, operator_headers: dict
):
    """OPERATOR lacks MANAGE_USERS, must be denied."""
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "elevatetarget@example.com",
            "password": "password123",
            "full_name": "Elevate Target",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/elevate",
        json={"new_role": "admin"},
        headers=operator_headers,
    )
    assert response.status_code == 403


async def test_admin_can_set_department(client: AsyncClient, admin_headers: dict):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "deptarget@example.com",
            "password": "password123",
            "full_name": "Dept Target",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/department",
        json={"department": "Radiology"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["department"] == "Radiology"


async def test_set_department_404_for_missing_user(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/auth/users/00000000-0000-0000-0000-000000000000/department",
        json={"department": "Radiology"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_front_desk_cannot_set_department(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "deptarget2@example.com",
            "password": "password123",
            "full_name": "Dept Target 2",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/department",
        json={"department": "Radiology"},
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_set_department_rejects_empty_string(client: AsyncClient, admin_headers: dict):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "deptarget3@example.com",
            "password": "password123",
            "full_name": "Dept Target 3",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/department",
        json={"department": ""},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_admin_can_list_users(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "listendpoint1@example.com",
            "password": "password123",
            "full_name": "List Endpoint User",
        },
    )

    response = await client.get("/api/v1/auth/users", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    emails = {item["email"] for item in body["items"]}
    assert "listendpoint1@example.com" in emails
    item = next(i for i in body["items"] if i["email"] == "listendpoint1@example.com")
    assert "last_active" in item
    assert item["last_active"] is None


async def test_list_users_search_query_param(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "searchable@example.com",
            "password": "password123",
            "full_name": "Very Searchable Name",
        },
    )

    response = await client.get(
        "/api/v1/auth/users", params={"search": "Very Searchable"}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "searchable@example.com"


async def test_front_desk_cannot_list_users(client: AsyncClient, front_desk_headers: dict):
    response = await client.get("/api/v1/auth/users", headers=front_desk_headers)
    assert response.status_code == 403


async def test_operator_cannot_list_users(client: AsyncClient, operator_headers: dict):
    """MANAGE_USERS has no operator grant path, must be denied."""
    response = await client.get("/api/v1/auth/users", headers=operator_headers)
    assert response.status_code == 403


async def test_elevate_writes_audit_event(
    client: AsyncClient, admin_headers: dict, admin_user: User, db_session
):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "elevateaudit@example.com",
            "password": "password123",
            "full_name": "Elevate Audit Target",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/elevate",
        json={"new_role": "operator"},
        headers=admin_headers,
    )
    assert response.status_code == 200

    # actor_id scopes to this test's own fresh admin_user, so a leftover
    # "user.role_changed" row from prior manual/smoke-test traffic against
    # a shared dev database (a real thing that happened during this same
    # phase's own live smoke test) can't leak into this count, same pollution
    # class as the other scoping fixes in this suite.
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "user.role_changed",
                    AuditEvent.actor_id == admin_user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].details == {
        "user_id": user_id,
        "old_role": "front_desk",
        "new_role": "operator",
    }


async def test_set_active_status_toggles_and_persists(client: AsyncClient, admin_headers: dict):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "toggle-me@example.com",
            "password": "password123",
            "full_name": "Toggle Me",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/active",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    listing = await client.get(
        "/api/v1/auth/users", params={"search": "toggle-me"}, headers=admin_headers
    )
    assert listing.json()["items"][0]["is_active"] is False


async def test_set_active_status_404_for_missing_user(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/auth/users/00000000-0000-0000-0000-000000000000/active",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_front_desk_cannot_set_active_status(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "toggle-target2@example.com",
            "password": "password123",
            "full_name": "Toggle Target 2",
        },
    )
    user_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/auth/users/{user_id}/active",
        json={"is_active": False},
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_get_user_grants_returns_real_grants(client: AsyncClient, admin_headers: dict):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "grants-target@example.com",
            "password": "password123",
            "full_name": "Grants Target",
        },
    )
    user_id = reg.json()["id"]

    grants = await client.get(f"/api/v1/auth/users/{user_id}/grants", headers=admin_headers)
    assert grants.status_code == 200
    assert grants.json()["permissions"] == []


async def test_get_user_grants_404_for_missing_user(client: AsyncClient, admin_headers: dict):
    response = await client.get(
        "/api/v1/auth/users/00000000-0000-0000-0000-000000000000/grants",
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_front_desk_cannot_get_user_grants(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    reg = await client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "grants-target2@example.com",
            "password": "password123",
            "full_name": "Grants Target 2",
        },
    )
    user_id = reg.json()["id"]

    response = await client.get(f"/api/v1/auth/users/{user_id}/grants", headers=front_desk_headers)
    assert response.status_code == 403


async def test_a_service_account_on_a_reserved_domain_does_not_500(
    client: AsyncClient, db_session, admin_headers: dict
):
    """A script-created service account can hold an address that email-validator
    refuses as undeliverable (.local is reserved, RFC 6762). User.email is an
    unvalidated String(255), so the row exists; validating it again on the way
    OUT turned it into a 500 on /auth/me and on any /auth/users page containing
    it. Registration still validates, which is where the check belongs.
    """
    from app.auth.security import create_access_token, hash_password
    from app.models import User, UserRole

    bot = User(
        email="outlook-connector@vitalai.local",
        hashed_password=hash_password("pass1234"),
        full_name="Outlook Connector",
        role=UserRole.ADMIN,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {create_access_token(bot.id, bot.role)}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "outlook-connector@vitalai.local"

    # routes/auth.py validates every row, so one bad row used to break the page.
    listing = await client.get("/api/v1/auth/users", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    assert any(u["email"] == "outlook-connector@vitalai.local" for u in listing.json()["items"])


async def test_register_without_a_login_is_refused(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "liam.obrien84@gmail.com",
            "password": "password123",
            "full_name": "Liam O'Brien",
        },
    )
    assert response.status_code == 401


async def test_register_as_front_desk_is_refused(client: AsyncClient, front_desk_headers: dict):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "chloe.nguyen@harbourviewmedical.com.au",
            "password": "password123",
            "full_name": "Chloe Nguyen",
        },
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_an_admin_creating_an_account_is_audited(
    client: AsyncClient, admin_headers: dict, db_session
):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "marcus.patel@harbourviewmedical.com.au",
            "password": "password123",
            "full_name": "Marcus Patel",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    event = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.action == "user.created"))
    ).scalar_one()
    assert event.details["user_id"] == response.json()["id"]
    assert event.details["role"] == "front_desk"
