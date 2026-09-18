import pytest

from app.config import settings
from app.services import settings_service


@pytest.fixture(autouse=True)
def _restore_settings_singleton():
    """PATCH /settings mutates the process-wide `settings` singleton by design;
    without this, a write here leaks into every test that runs afterward in
    the same pytest session (see tests/test_settings_service.py's copy)."""
    snapshot = {key: getattr(settings, key) for key in settings_service.SETTINGS_REGISTRY}
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


@pytest.mark.asyncio
async def test_admin_can_read_settings(client, admin_headers):
    res = await client.get("/api/v1/settings", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    keys = {item["key"] for item in body["items"]}
    assert "task_routing_auto_threshold" in keys

    entry = next(i for i in body["items"] if i["key"] == "task_routing_auto_threshold")
    assert entry["group"] == "Approval tiers"
    assert entry["editable"] is True
    assert entry["default"] == 0.90
    assert entry["minimum"] == 0.0 and entry["maximum"] == 1.0


@pytest.mark.asyncio
async def test_read_only_settings_are_marked(client, admin_headers):
    res = await client.get("/api/v1/settings", headers=admin_headers)
    entry = next(i for i in res.json()["items"] if i["key"] == "sufficiency_floor")
    assert entry["editable"] is False


@pytest.mark.asyncio
async def test_operator_cannot_read_settings(client, operator_headers):
    res = await client.get("/api/v1/settings", headers=operator_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_doctor_cannot_write_settings(client, doctor_headers):
    res = await client.patch(
        "/api/v1/settings", json={"values": {"clinic_open_hour": 7}}, headers=doctor_headers
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_write_and_read_back(client, admin_headers):
    res = await client.patch(
        "/api/v1/settings", json={"values": {"clinic_open_hour": 7}}, headers=admin_headers
    )
    assert res.status_code == 200

    res = await client.get("/api/v1/settings", headers=admin_headers)
    entry = next(i for i in res.json()["items"] if i["key"] == "clinic_open_hour")
    assert entry["value"] == 7
    assert entry["default"] == 8
    assert entry["updated_by"] is not None


@pytest.mark.asyncio
async def test_invalid_value_returns_422_and_changes_nothing(client, admin_headers):
    res = await client.patch(
        "/api/v1/settings",
        json={"values": {"task_routing_auto_threshold": 5}},
        headers=admin_headers,
    )
    assert res.status_code == 422

    res = await client.get("/api/v1/settings", headers=admin_headers)
    entry = next(i for i in res.json()["items"] if i["key"] == "task_routing_auto_threshold")
    assert entry["value"] == 0.90


@pytest.mark.asyncio
async def test_writing_a_read_only_setting_returns_422(client, admin_headers):
    res = await client.patch(
        "/api/v1/settings", json={"values": {"sufficiency_floor": 0.2}}, headers=admin_headers
    )
    assert res.status_code == 422
