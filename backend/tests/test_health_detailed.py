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


@pytest.mark.asyncio
async def test_llm_row_probes_bedrock_when_bedrock_is_the_provider(
    client, admin_headers, monkeypatch
):
    from app.config import settings
    from app.services import health_service

    monkeypatch.setattr(settings, "llm_provider", "bedrock")
    monkeypatch.setattr(settings, "bedrock_model_id", "au.anthropic.test-model")
    calls = []
    monkeypatch.setattr(health_service, "_probe_bedrock_sync", lambda: calls.append(1))

    res = await client.get("/api/v1/health/detailed", headers=admin_headers)

    assert res.status_code == 200
    llm = next(s for s in res.json()["services"] if s["name"] == "LLM provider")
    assert llm["status"] == "operational"
    assert llm["detail"] == "bedrock: au.anthropic.test-model"
    assert calls == [1]


@pytest.mark.asyncio
async def test_llm_row_is_down_not_an_error_when_bedrock_fails(client, admin_headers, monkeypatch):
    from app.config import settings
    from app.services import health_service

    def refused():
        raise RuntimeError("AccessDeniedException: model access not granted")

    monkeypatch.setattr(settings, "llm_provider", "bedrock")
    monkeypatch.setattr(health_service, "_probe_bedrock_sync", refused)

    res = await client.get("/api/v1/health/detailed", headers=admin_headers)

    assert res.status_code == 200
    llm = next(s for s in res.json()["services"] if s["name"] == "LLM provider")
    assert llm["status"] == "down"
    assert "AccessDeniedException" in llm["note"]


@pytest.mark.asyncio
async def test_a_slow_but_working_bedrock_is_operational(client, admin_headers, monkeypatch):
    """A cross-region call with a fresh connection can take a few seconds; the
    other services' 3 s cut-off would paint a working model red."""
    import time

    from app.config import settings
    from app.services import health_service

    monkeypatch.setattr(settings, "llm_provider", "bedrock")
    monkeypatch.setattr(health_service, "_probe_bedrock_sync", lambda: time.sleep(3.5))

    res = await client.get("/api/v1/health/detailed", headers=admin_headers)

    llm = next(s for s in res.json()["services"] if s["name"] == "LLM provider")
    assert llm["status"] == "operational"


@pytest.mark.asyncio
async def test_a_bedrock_timeout_says_so(client, admin_headers, monkeypatch):
    import time

    from app.config import settings
    from app.services import health_service

    monkeypatch.setattr(settings, "llm_provider", "bedrock")
    monkeypatch.setattr(health_service, "_BEDROCK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(health_service, "_probe_bedrock_sync", lambda: time.sleep(1))

    res = await client.get("/api/v1/health/detailed", headers=admin_headers)

    llm = next(s for s in res.json()["services"] if s["name"] == "LLM provider")
    assert llm["status"] == "down"
    assert llm["note"] == "TimeoutError"
