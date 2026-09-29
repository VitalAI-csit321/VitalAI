from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.auth.security import create_password_reset_token, verify_password
from app.limiter import limiter
from app.models.audit import AuditEvent
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


@pytest.mark.asyncio
async def test_reset_email_goes_through_the_audited_send_path(
    db_session, admin_user, detached_sessionmaker, monkeypatch
):
    """email_service.deliver_new_message is the one caller of send_mail: the
    send is audited there, and the event never carries the link, which is a
    live credential for half an hour."""
    monkeypatch.setattr(auth_routes, "AsyncSessionLocal", detached_sessionmaker)
    monkeypatch.setattr(auth_routes.settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    mails = AsyncMock()
    monkeypatch.setattr("app.services.outlook_client.send_mail", mails)

    await auth_routes._send_reset_link("admin@example.com", "http://x/reset-password?token=s3cret")

    [call] = mails.await_args_list
    _, to_address, _, body = call.args
    assert to_address == "admin@example.com"
    assert "token=s3cret" in body
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == admin_user.id)))
        .scalars()
        .all()
    )
    [sent] = [e for e in events if e.action == "auth.password_reset_sent"]
    assert sent.details["delivered"] is True
    assert "s3cret" not in str(sent.details)
