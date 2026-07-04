from httpx import AsyncClient


async def test_register_then_login(client: AsyncClient):
    register_response = await client.post(
        "/api/v1/auth/register",
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


async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
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


async def test_register_duplicate_email(client: AsyncClient):
    payload = {
        "email": "dupe@example.com",
        "password": "password123",
        "full_name": "Dupe",
        "role": "front_desk",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_protected_endpoint_requires_token(client: AsyncClient):
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "x",
            "contact_reason": "y",
            "contact_channel": "phone",
        },
    )
    assert response.status_code == 401


async def test_register_ignores_role_in_payload(client: AsyncClient):
    """Sending role=admin in the register payload must still result in front_desk."""
    response = await client.post(
        "/api/v1/auth/register",
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
        json={"new_role": "ops_manager"},
        headers=admin_headers,
    )
    assert elevate.status_code == 200
    assert elevate.json()["role"] == "ops_manager"


async def test_front_desk_cannot_elevate_role(client: AsyncClient, front_desk_headers: dict):
    reg = await client.post(
        "/api/v1/auth/register",
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
