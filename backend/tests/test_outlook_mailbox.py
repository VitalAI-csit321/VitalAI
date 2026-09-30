"""Clinic mailbox status and the Settings "Sign in with Microsoft" reconnect.

Microsoft is faked: build_app returns an object with the two MSAL auth-code
calls, and the token cache is never written to disk.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.audit import AuditEvent
from app.services import health_service, outlook_auth, outlook_poller
from app.services.outlook_auth import OutlookAuthRequiredError

CALLBACK = "/api/v1/integrations/outlook/callback"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(outlook_poller, "status", outlook_poller.PollerStatus())
    outlook_auth._pending.clear()
    monkeypatch.setattr(outlook_auth, "connected_account", lambda: None)


async def _one_cycle(monkeypatch, poll) -> None:
    async def stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(outlook_poller, "poll_once", poll)
    monkeypatch.setattr(outlook_poller.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await outlook_poller.run_poller()


@pytest.mark.asyncio
async def test_the_poller_records_a_successful_check(monkeypatch):
    async def ok():
        return None

    await _one_cycle(monkeypatch, ok)
    assert outlook_poller.status.last_ok_at is not None
    assert outlook_poller.status.needs_signin is False


@pytest.mark.asyncio
async def test_the_poller_flags_an_expired_sign_in(monkeypatch):
    async def expired():
        raise OutlookAuthRequiredError("refresh token expired")

    await _one_cycle(monkeypatch, expired)
    assert outlook_poller.status.needs_signin is True
    assert outlook_poller.status.last_ok_at is None


def _probe(monkeypatch, *, enabled=True, **status):
    monkeypatch.setattr(settings, "outlook_enabled", enabled)
    monkeypatch.setattr(outlook_poller, "status", outlook_poller.PollerStatus(**status))
    return health_service._probe_outlook()


def test_operations_reports_what_the_poller_saw(monkeypatch):
    now = datetime.now(UTC)
    assert _probe(monkeypatch, enabled=False).status == "disabled"
    assert _probe(monkeypatch, needs_signin=True).status == "down"
    assert _probe(monkeypatch).status == "degraded"  # enabled, never checked
    assert _probe(monkeypatch, last_ok_at=now).status == "operational"
    stale = now - timedelta(seconds=4 * settings.outlook_poll_interval_seconds)
    assert _probe(monkeypatch, last_ok_at=stale).status == "degraded"


@pytest.mark.asyncio
async def test_mailbox_status_is_admin_only(client, admin_headers, operator_headers, monkeypatch):
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr(outlook_auth, "connected_account", lambda: "clinic@outlook.com")
    res = await client.get("/api/v1/integrations/outlook", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["account"] == "clinic@outlook.com"
    assert body["needs_signin"] is False
    forbidden = await client.get("/api/v1/integrations/outlook", headers=operator_headers)
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_an_enabled_mailbox_with_no_account_needs_sign_in(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "outlook_enabled", True)
    res = await client.get("/api/v1/integrations/outlook", headers=admin_headers)
    assert res.json()["needs_signin"] is True


class FakeMicrosoft:
    def __init__(self):
        self.redirect_uri = None
        self.result = {
            "access_token": "t",
            "id_token_claims": {"preferred_username": "clinic@outlook.com"},
        }

    def initiate_auth_code_flow(self, scopes, redirect_uri=None, **_):
        self.redirect_uri = redirect_uri
        return {"auth_uri": "https://login.example/authorize?s=abc", "state": "abc"}

    def acquire_token_by_auth_code_flow(self, flow, params, **_):
        if "error" in params:
            return {"error": params["error"]}
        return self.result


@pytest.fixture
def microsoft(monkeypatch):
    fake = FakeMicrosoft()
    saved = []
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr(outlook_auth, "build_app", lambda cache: fake)
    monkeypatch.setattr(outlook_auth, "save_cache", lambda cache: saved.append(cache))
    fake.saved = saved
    return fake


def _outcome(res) -> str:
    assert res.status_code in (302, 303, 307)
    url = urlparse(res.headers["location"])
    assert url.path == "/settings"
    return parse_qs(url.query)["mailbox"][0]


@pytest.mark.asyncio
async def test_connect_sends_the_admin_to_microsoft(client, admin_headers, microsoft):
    res = await client.post("/api/v1/integrations/outlook/connect", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["auth_url"].startswith("https://login.example/")
    assert microsoft.redirect_uri.endswith(CALLBACK)


@pytest.mark.asyncio
async def test_connect_is_refused_where_email_is_off(client, admin_headers, microsoft, monkeypatch):
    monkeypatch.setattr(settings, "outlook_enabled", False)
    res = await client.post("/api/v1/integrations/outlook/connect", headers=admin_headers)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_the_callback_saves_the_sign_in_and_returns_to_settings(
    client, admin_headers, microsoft, db_session
):
    outlook_poller.status.needs_signin = True
    await client.post("/api/v1/integrations/outlook/connect", headers=admin_headers)
    res = await client.get(f"{CALLBACK}?code=c&state=abc", follow_redirects=False)
    assert _outcome(res) == "connected"
    assert len(microsoft.saved) == 1
    assert outlook_poller.status.needs_signin is False
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "integrations.outlook_connected")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1

    # A sign-in finishes once; replaying the redirect does nothing.
    again = await client.get(f"{CALLBACK}?code=c&state=abc", follow_redirects=False)
    assert _outcome(again) == "error"
    assert len(microsoft.saved) == 1


@pytest.mark.asyncio
async def test_an_unknown_sign_in_is_rejected(client, microsoft):
    res = await client.get(f"{CALLBACK}?code=c&state=forged", follow_redirects=False)
    assert _outcome(res) == "error"
    assert microsoft.saved == []


@pytest.mark.asyncio
async def test_a_cancelled_sign_in_changes_nothing(client, admin_headers, microsoft):
    await client.post("/api/v1/integrations/outlook/connect", headers=admin_headers)
    res = await client.get(f"{CALLBACK}?error=access_denied&state=abc", follow_redirects=False)
    assert _outcome(res) == "error"
    assert microsoft.saved == []
