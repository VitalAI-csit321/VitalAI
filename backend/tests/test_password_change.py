import pytest

from app.auth.security import verify_password


@pytest.mark.asyncio
async def test_change_password_succeeds_and_new_password_authenticates(
    client, db_session, admin_user, admin_headers
):
    res = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "password123", "new_password": "BrandNewPass456"},
        headers=admin_headers,
    )
    assert res.status_code == 204

    await db_session.refresh(admin_user)
    assert verify_password("BrandNewPass456", admin_user.hashed_password)


@pytest.mark.asyncio
async def test_wrong_current_password_is_rejected(client, admin_headers):
    res = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "not-my-password", "new_password": "BrandNewPass456"},
        headers=admin_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_reusing_the_current_password_is_rejected(client, admin_headers):
    res = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "password123", "new_password": "password123"},
        headers=admin_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_short_password_is_rejected(client, admin_headers):
    res = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "password123", "new_password": "short"},
        headers=admin_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(client):
    res = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "x" * 12, "new_password": "y" * 12},
    )
    assert res.status_code == 401
