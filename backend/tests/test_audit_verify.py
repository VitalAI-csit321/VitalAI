from httpx import AsyncClient
from sqlalchemy import text

from app.models import Patient


async def test_verify_requires_read_audit_permission(client: AsyncClient, front_desk_headers: dict):
    response = await client.get("/api/v1/audit/verify", headers=front_desk_headers)
    assert response.status_code == 403


async def test_verify_reports_valid_on_untampered_chain(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/audit/verify", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["checked_count"] >= 1
    assert body["first_break_event_id"] is None


async def test_verify_detects_tampering(
    client: AsyncClient, admin_headers: dict, patient: Patient, db_session
):
    create = await client.post(
        "/api/v1/intake",
        json={"patient_id": str(patient.id), "contact_reason": "Visit", "contact_channel": "phone"},
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    from sqlalchemy import select

    from app.models.audit import AuditEvent

    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.case_id == case_id, AuditEvent.action == "intake.created"
            )
        )
    ).scalar_one()

    await db_session.execute(
        text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update")
    )
    await db_session.execute(
        text("UPDATE audit_events SET event_hash = 'tampered0000' WHERE id = :id"),
        {"id": event.id},
    )
    await db_session.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update"))
    await db_session.commit()

    response = await client.get("/api/v1/audit/verify", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["first_break_event_id"] == str(event.id)
