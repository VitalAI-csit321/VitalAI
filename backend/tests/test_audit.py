from httpx import AsyncClient


async def test_get_audit_trail_for_case(client: AsyncClient, admin_headers: dict):
    """GET /audit/by-case must return the actual recorded events, not just 200."""
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "Audit Tester",
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
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    """The audit trail is admin-only — front_desk must be denied."""
    create = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "Audit Tester",
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=admin_headers,
    )
    case_id = create.json()["id"]

    response = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=front_desk_headers)
    assert response.status_code == 403
