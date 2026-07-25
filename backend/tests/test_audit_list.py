from httpx import AsyncClient

from app.models import Patient, User


async def test_list_audit_events_requires_read_audit_permission(
    client: AsyncClient, front_desk_headers: dict
):
    response = await client.get("/api/v1/audit", headers=front_desk_headers)
    assert response.status_code == 403


async def test_list_audit_events_returns_real_events(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    create = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    assert create.status_code == 201

    response = await client.get("/api/v1/audit?limit=50", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    actions = [item["action"] for item in body["items"]]
    assert "intake.created" in actions

    intake_event = next(item for item in body["items"] if item["action"] == "intake.created")
    assert intake_event["risk_level"] == "Low"
    assert intake_event["outcome"] == "SUCCESS"
    assert intake_event["event_hash"] is not None


async def test_list_audit_events_filters_by_action(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/audit?action=intake.created", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert all(item["action"] == "intake.created" for item in body["items"])


async def test_list_audit_events_filters_by_risk_level(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    # A denied request writes a governance.access_denied event, risk_score 90 -> High.
    await client.get(
        "/api/v1/audit", headers=front_desk_headers
    )  # this itself 403s and logs a denial

    response = await client.get("/api/v1/audit?risk_level=High", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1
    assert all(item["risk_level"] == "High" for item in body["items"])


async def test_listing_audit_events_is_itself_logged(
    client: AsyncClient, admin_headers: dict, admin_user: User, db_session
):
    from sqlalchemy import select

    from app.models.audit import AuditEvent

    await client.get("/api/v1/audit", headers=admin_headers)

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "audit.list_read", AuditEvent.actor_id == admin_user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
