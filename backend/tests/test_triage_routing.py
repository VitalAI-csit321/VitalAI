import uuid

import pytest
from httpx import AsyncClient


async def _create_case(client: AsyncClient, headers: dict, reason: str = "general") -> str:
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "Triage Tester",
            "contact_reason": reason,
            "contact_channel": "phone",
        },
        headers=headers,
    )
    return response.json()["id"]


async def _capture_consent(client: AsyncClient, headers: dict, case_id: str) -> None:
    """Create and capture consent for a case so triage is permitted."""
    create = await client.post(
        "/api/v1/consent",
        json={"case_id": case_id},
        headers=headers,
    )
    consent_id = create.json()["id"]
    await client.post(f"/api/v1/consent/{consent_id}/capture", headers=headers)


async def _case_with_consent(client: AsyncClient, headers: dict, reason: str = "general") -> str:
    """Create a case and capture consent; return the case_id."""
    case_id = await _create_case(client, headers, reason)
    await _capture_consent(client, headers, case_id)
    return case_id


async def test_triage_routine(client: AsyncClient, admin_headers: dict):
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "I would like to update my address on file please",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "routine"
    assert body["escalated"] is False
    assert body["routing_action"] == "admin_workflow"


async def test_triage_urgent_keyword(client: AsyncClient, admin_headers: dict):
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "this is urgent please call back",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.json()["category"] == "immediate"
    assert response.json()["escalated"] is True


async def test_triage_multi_word_phrase_chest_pain(client: AsyncClient, admin_headers: dict):
    """Regression: original code did set intersection on whitespace tokens,
    so 'chest pain' never matched. Substring match fixes it."""
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "patient reports chest pain and dizziness",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.json()["category"] == "immediate"


async def test_triage_patient_flag_escalates(client: AsyncClient, admin_headers: dict):
    """Regression: original code treated patient priority flags as a
    low-confidence signal. They should escalate, not de-escalate."""
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "need to reschedule appointment next week",
            "keywords": [],
            "patient_priority_flags": ["high_priority_patient"],
        },
        headers=admin_headers,
    )
    assert response.json()["category"] == "time_sensitive"
    assert response.json()["escalated"] is True


@pytest.mark.xfail(
    reason="TODO(Phase 3): _matches_any has no negation handling — 'not urgent' hits the urgent keyword and incorrectly escalates"
)
async def test_triage_negation_not_urgent_escalates_incorrectly(
    client: AsyncClient, admin_headers: dict
):
    """'not urgent' should be routine but the substring match hits 'urgent'."""
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "this is not urgent, just a routine billing question",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.json()["category"] == "routine"


async def test_triage_then_routing(client: AsyncClient, admin_headers: dict):
    case_id = await _case_with_consent(
        client, admin_headers, "regular check up booking please thanks"
    )
    triage = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "regular check up booking please thanks",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    triage_id = triage.json()["triage_id"]

    routing = await client.post(
        "/api/v1/routing",
        json={"triage_id": triage_id},
        headers=admin_headers,
    )
    assert routing.status_code == 201
    assert routing.json()["action"] == "admin_workflow"
    assert routing.json()["case_id"] == case_id
    assert routing.json()["triage_id"] == triage_id


async def test_routing_triage_not_found_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/routing",
        json={"triage_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_get_routing_decision_by_case(client: AsyncClient, admin_headers: dict):
    case_id = await _case_with_consent(
        client, admin_headers, "regular check up booking please thanks"
    )
    triage = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "regular check up booking please thanks",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    triage_id = triage.json()["triage_id"]
    routing = await client.post(
        "/api/v1/routing",
        json={"triage_id": triage_id},
        headers=admin_headers,
    )

    response = await client.get(f"/api/v1/routing/by-case/{case_id}", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == case_id
    assert body["triage_id"] == triage_id
    assert body["action"] == routing.json()["action"]
    assert body["escalated"] == routing.json()["escalated"]


# ---------------------------------------------------------------------------
# Consent gating tests
# ---------------------------------------------------------------------------


async def test_triage_blocked_when_no_consent_record(client: AsyncClient, admin_headers: dict):
    """Triage must be rejected when no consent record exists for the case."""
    case_id = await _create_case(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "routine inquiry",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


async def test_triage_blocked_when_consent_withdrawn(client: AsyncClient, admin_headers: dict):
    """Triage must be rejected when consent has been withdrawn."""
    case_id = await _create_case(client, admin_headers)

    # Create consent, capture it, then withdraw.
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]
    await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)

    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "routine inquiry",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "withdrawn" in response.json()["detail"].lower()


async def test_triage_blocked_when_consent_pending(client: AsyncClient, admin_headers: dict):
    """Triage must be rejected when consent is pending (not yet captured)."""
    case_id = await _create_case(client, admin_headers)
    await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)

    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "routine inquiry",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_triage_allowed_when_consent_captured(client: AsyncClient, admin_headers: dict):
    """Positive gate: triage proceeds normally when consent is captured."""
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "book appointment",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["case_id"] == case_id


async def test_routing_post_denied_for_front_desk(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    """FRONT_DESK lacks MANAGE_CASES, must be denied creating a routing decision."""
    case_id = await _case_with_consent(
        client, admin_headers, "regular check up booking please thanks"
    )
    triage = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "regular check up booking please thanks",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    triage_id = triage.json()["triage_id"]

    response = await client.post(
        "/api/v1/routing", json={"triage_id": triage_id}, headers=front_desk_headers
    )
    assert response.status_code == 403


async def test_routing_get_allowed_for_front_desk(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict
):
    """FRONT_DESK has VIEW_QUEUE, must be allowed to read a routing decision."""
    case_id = await _case_with_consent(
        client, admin_headers, "regular check up booking please thanks"
    )
    triage = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "regular check up booking please thanks",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=admin_headers,
    )
    triage_id = triage.json()["triage_id"]
    await client.post("/api/v1/routing", json={"triage_id": triage_id}, headers=admin_headers)

    response = await client.get(f"/api/v1/routing/by-case/{case_id}", headers=front_desk_headers)
    assert response.status_code == 200


async def test_triage_denied_for_front_desk(client: AsyncClient, admin_headers: dict, front_desk_headers: dict):
    """FRONT_DESK lacks MANAGE_CASES, must be denied running triage."""
    case_id = await _case_with_consent(client, admin_headers)
    response = await client.post(
        "/api/v1/triage",
        json={
            "case_id": case_id,
            "contact_reason": "routine inquiry",
            "keywords": [],
            "patient_priority_flags": [],
        },
        headers=front_desk_headers,
    )
    assert response.status_code == 403
