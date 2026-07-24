from httpx import AsyncClient
from sqlalchemy import select

from app.models import Patient, User
from app.models.audit import AuditEvent


async def test_get_audit_trail_for_case(client: AsyncClient, admin_headers: dict, patient: Patient):
    """GET /audit/by-case must return the actual recorded events, not just 200."""
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    consent = await client.post(
        "/api/v1/consent",
        json={"case_id": case_id},
        headers=admin_headers,
    )
    consent_id = consent.json()["id"]
    await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)

    response = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert response.status_code == 200
    events = response.json()
    actions = [event["action"] for event in events]
    assert actions == ["intake.created", "consent.created", "consent.captured"]
    assert all(event["case_id"] == case_id for event in events)


async def test_get_audit_trail_denied_for_non_admin(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict, patient: Patient
):
    """The audit trail is admin-only, front_desk must be denied."""
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=front_desk_headers)
    assert response.status_code == 403


async def test_get_audit_trail_denied_for_operator_without_grant(
    client: AsyncClient, admin_headers: dict, operator_headers: dict, patient: Patient
):
    """OPERATOR without the READ_AUDIT grant must be denied."""
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=operator_headers)
    assert response.status_code == 403


async def test_reading_audit_trail_is_itself_logged(
    client: AsyncClient, admin_headers: dict, admin_user: User, patient: Patient, db_session
):
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    first_read = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert first_read.status_code == 200
    # The read event fires AFTER the query that produced this response, so it must not
    # appear in this response's own event list.
    assert "audit.read" not in [e["action"] for e in first_read.json()]

    # actor_id scopes to this test's own fresh admin_user, so leftover "audit.read"
    # rows from prior manual/smoke-test traffic against a shared dev database
    # (a real thing that happened during this same phase's own live smoke test,
    # which exercised this exact route) can't leak into this count.
    read_events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "audit.read", AuditEvent.actor_id == admin_user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(read_events) == 1
    assert str(read_events[0].case_id) == case_id
    assert read_events[0].details == {"case_id": case_id}

    # A second read now sees the first read's own audit.read event.
    second_read = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    actions = [e["action"] for e in second_read.json()]
    assert actions.count("audit.read") == 1


async def test_reading_audit_trail_logs_even_for_nonexistent_case(
    client: AsyncClient, admin_headers: dict, admin_user: User, db_session
):
    """A read attempt is logged even against a case_id that doesn't exist.

    audit_events.case_id has a real FK to intake_cases, so the logged event's
    case_id column must fall back to NULL here rather than the bogus id
    (which would violate the FK) - the attempted id still lands in details.
    """
    nonexistent_case_id = "00000000-0000-0000-0000-000000000000"

    response = await client.get(
        f"/api/v1/audit/by-case/{nonexistent_case_id}", headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json() == []

    # case_id is NULL on this event (see the docstring), so unlike the sibling
    # test this can't be scoped by case_id; actor_id scopes to this test's own
    # fresh admin_user instead, for the same pollution reason as that test.
    read_events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "audit.read", AuditEvent.actor_id == admin_user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(read_events) == 1
    assert read_events[0].case_id is None
    assert read_events[0].details == {"case_id": nonexistent_case_id}
