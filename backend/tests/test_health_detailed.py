import pytest


@pytest.mark.asyncio
async def test_plain_health_is_still_public_and_unchanged(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_detailed_health_requires_permission(client, front_desk_headers):
    res = await client.get("/api/v1/health/detailed", headers=front_desk_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_detailed_health_is_unauthenticated_rejected(client):
    res = await client.get("/api/v1/health/detailed")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_admin_gets_service_list_and_metrics(client, admin_headers):
    res = await client.get("/api/v1/health/detailed", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()

    names = {s["name"] for s in body["services"]}
    assert {"Database", "Object storage", "LLM provider", "Outlook connector"} <= names

    db = next(s for s in body["services"] if s["name"] == "Database")
    assert db["status"] == "operational"
    assert db["latency_ms"] is not None

    assert "uptime_seconds" in body
    assert "latency" in body and "avg_ms" in body["latency"]
    assert "active_sessions" in body


@pytest.mark.asyncio
async def test_outlook_reports_disabled_rather_than_down_when_off(client, admin_headers):
    """A connector switched off is not a failure, and must not show as red."""
    from app.config import settings

    original = settings.outlook_enabled
    try:
        settings.outlook_enabled = False
        res = await client.get("/api/v1/health/detailed", headers=admin_headers)
        outlook = next(s for s in res.json()["services"] if s["name"] == "Outlook connector")
        assert outlook["status"] == "disabled"
    finally:
        settings.outlook_enabled = original


@pytest.mark.asyncio
async def test_a_dependency_being_down_does_not_fail_the_endpoint(
    client, admin_headers, monkeypatch
):
    """One unreachable service must degrade its own row, never 500 the page."""
    from app.services import health_service

    def boom():
        raise OSError("connection refused")

    monkeypatch.setattr(health_service, "_probe_object_storage_sync", boom)
    res = await client.get("/api/v1/health/detailed", headers=admin_headers)
    assert res.status_code == 200
    storage = next(s for s in res.json()["services"] if s["name"] == "Object storage")
    assert storage["status"] == "down"
