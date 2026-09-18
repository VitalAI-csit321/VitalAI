import pytest

from app.services import audit_service


@pytest.mark.asyncio
async def test_incidents_returns_only_blocked_events(client, db_session, admin_user, admin_headers):
    await audit_service.record_event(
        db_session, action="governance.access_denied", actor=admin_user, details={"why": "rbac"}
    )
    await audit_service.record_event(
        db_session, action="patient.viewed", actor=admin_user, details={}
    )
    await db_session.commit()

    res = await client.get("/api/v1/audit/incidents", headers=admin_headers)
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 1
    assert all(i["outcome"] == "BLOCKED" for i in items)
    assert any(i["action"] == "governance.access_denied" for i in items)


@pytest.mark.asyncio
async def test_incidents_are_newest_first(client, db_session, admin_user, admin_headers):
    for i in range(3):
        await audit_service.record_event(
            db_session,
            action="governance.input_blocked",
            actor=admin_user,
            details={"n": i},
        )
    await db_session.commit()

    res = await client.get("/api/v1/audit/incidents?limit=3", headers=admin_headers)
    items = res.json()["items"]
    assert len(items) == 3
    assert [i["details"]["n"] for i in items] == [2, 1, 0]


@pytest.mark.asyncio
async def test_incidents_requires_read_audit(client, front_desk_headers):
    res = await client.get("/api/v1/audit/incidents", headers=front_desk_headers)
    assert res.status_code == 403
