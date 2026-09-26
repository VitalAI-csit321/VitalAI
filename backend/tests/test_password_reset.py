import pytest

from app.auth.security import create_password_reset_token, verify_password
from app.limiter import limiter
from app.routes import auth as auth_routes


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    limiter.reset()


@pytest.fixture
def sent_links(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_send(email: str, link: str) -> None:
        sent.append((email, link))

    monkeypatch.setattr(auth_routes, "_send_reset_link", fake_send)
    return sent


@pytest.mark.asyncio
async def test_full_reset_flow_and_link_is_single_use(client, db_session, admin_user, sent_links):
    res = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "admin@example.com"}
    )
    assert res.status_code == 202
    [(email, link)] = sent_links
    assert email == "admin@example.com"
    token = link.split("token=", 1)[1]

    res = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "BrandNewPass456"},
    )
    assert res.status_code == 204
    await db_session.refresh(admin_user)
    assert verify_password("BrandNewPass456", admin_user.hashed_password)

    res = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "AnotherPass789"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_unknown_email_gets_same_response_and_no_mail(client, sent_links):
    res = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"}
    )
    assert res.status_code == 202
    assert sent_links == []


@pytest.mark.asyncio
async def test_garbage_token_is_rejected(client):
    res = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-token", "new_password": "BrandNewPass456"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_reset_token_is_not_an_access_token(client, admin_user):
    token = create_password_reset_token(admin_user.id, admin_user.hashed_password)
    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
