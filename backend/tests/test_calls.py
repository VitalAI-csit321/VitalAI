import json
import uuid
from typing import cast

from httpx import AsyncClient

from app.models import Patient


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        return self.response


def _mock_classifier(monkeypatch, category: str, confidence: float) -> None:
    monkeypatch.setattr(
        "app.services.call_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": category, "confidence": confidence})),
    )


async def _create_case(client: AsyncClient, headers: dict, patient: Patient) -> str:
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Manual call intake",
            "contact_channel": "phone",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return cast(str, response.json()["id"])


async def test_create_call_manual_entry(
    client: AsyncClient, front_desk_headers: dict, patient: Patient
):
    case_id = await _create_case(client, front_desk_headers, patient)

    response = await client.post(
        "/api/v1/calls",
        json={
            "case_id": case_id,
            "phone_number": "0412345678",
            "transcript": "Caller requested an appointment change.",
        },
        headers=front_desk_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["case_id"] == case_id
    assert body["phone_number"] == "0412345678"
    assert body["transcript"] == "Caller requested an appointment change."
    assert body["status"] == "received"


async def test_create_call_records_audit_event(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/calls",
        json={"case_id": case_id, "phone_number": "0399999999", "transcript": "Test"},
        headers=admin_headers,
    )
    assert response.status_code == 201

    audit = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    assert audit.status_code == 200
    assert "call.created" in [event["action"] for event in audit.json()]


async def test_create_call_rejects_missing_case(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/v1/calls",
        json={"case_id": str(uuid.uuid4()), "phone_number": "0412345678"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_list_calls_requires_view_queue(client: AsyncClient, doctor_headers: dict):
    response = await client.get("/api/v1/calls", headers=doctor_headers)
    assert response.status_code == 403


async def test_create_call_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/calls",
        json={"case_id": str(uuid.uuid4()), "phone_number": "0412345678"},
    )
    assert response.status_code == 401


async def test_create_call_requires_view_queue(
    client: AsyncClient,
    doctor_headers: dict,
):
    response = await client.post(
        "/api/v1/calls",
        json={
            "case_id": str(uuid.uuid4()),
            "phone_number": "0412345678",
            "transcript": "Doctor should not be allowed to create this call.",
        },
        headers=doctor_headers,
    )

    assert response.status_code == 403


async def _capture_consent(client: AsyncClient, headers: dict, case_id: str) -> None:
    created = await client.post(
        "/api/v1/consent",
        json={"case_id": case_id, "consent_type": "administrative"},
        headers=headers,
    )
    assert created.status_code == 201
    captured = await client.post(
        f"/api/v1/consent/{created.json()['id']}/capture",
        headers=headers,
    )
    assert captured.status_code == 200


async def _create_call(client: AsyncClient, headers: dict, case_id: str, transcript: str) -> dict:
    response = await client.post(
        "/api/v1/calls",
        json={
            "case_id": case_id,
            "phone_number": "0412345678",
            "transcript": transcript,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return cast(dict, response.json())


async def test_call_routing_flags_urgent_keywords_for_human_review(
    client: AsyncClient, operator_headers: dict, patient: Patient, monkeypatch
):
    # Category the fake classifier returns doesn't matter here: the urgent
    # keyword hard override in evaluate_task_routing_gate() fires regardless.
    _mock_classifier(monkeypatch, "general_administrative", 0.6)
    case_id = await _create_case(client, operator_headers, patient)
    await _capture_consent(client, operator_headers, case_id)
    call = await _create_call(
        client, operator_headers, case_id, "Caller reports chest pain and difficulty breathing."
    )

    response = await client.post(
        f"/api/v1/calls/{call['id']}/route", json={}, headers=operator_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "human_review"
    assert body["override_reason"] == "urgent_keyword"
    assert body["call"]["status"] == "processed"
    assert body["call"]["category"] == "general_administrative"


async def test_call_routing_auto_routes_high_confidence(
    client: AsyncClient, operator_headers: dict, patient: Patient, monkeypatch
):
    _mock_classifier(monkeypatch, "appointment_request", 0.95)
    case_id = await _create_case(client, operator_headers, patient)
    await _capture_consent(client, operator_headers, case_id)
    call = await _create_call(
        client, operator_headers, case_id, "Caller wants to book an appointment."
    )

    response = await client.post(
        f"/api/v1/calls/{call['id']}/route", json={}, headers=operator_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "auto_routed"
    assert body["category"] == "appointment_request"
    assert body["target_role"] == "front_desk"
    assert body["override_reason"] is None


async def test_call_routing_override_is_reversible_and_audited(
    client: AsyncClient, admin_headers: dict, patient: Patient, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    case_id = await _create_case(client, admin_headers, patient)
    await _capture_consent(client, admin_headers, case_id)
    call = await _create_call(client, admin_headers, case_id, "Routine appointment query.")
    routed = await client.post(f"/api/v1/calls/{call['id']}/route", json={}, headers=admin_headers)
    assert routed.status_code == 200

    override = await client.post(
        f"/api/v1/calls/{call['id']}/override-routing",
        json={"category": "referral_request", "reason": "Clinician reviewed, this is a referral"},
        headers=admin_headers,
    )
    assert override.status_code == 200
    assert override.json()["call"]["routing_overridden"] is True
    assert override.json()["target_role"] == "operator"

    reverse = await client.post(
        f"/api/v1/calls/{call['id']}/override-routing",
        json={"category": "general_administrative", "reason": "Reverting, was misrouted"},
        headers=admin_headers,
    )
    assert reverse.status_code == 200
    assert reverse.json()["target_role"] == "front_desk"

    audit = await client.get(f"/api/v1/audit/by-case/{case_id}", headers=admin_headers)
    actions = [event["action"] for event in audit.json()]
    assert actions.count("call.routing_overridden") == 2


async def test_call_escalation_transitions_the_routed_task_to_escalated(
    client: AsyncClient, operator_headers: dict, patient: Patient, monkeypatch
):
    _mock_classifier(monkeypatch, "urgent_emergency", 0.95)
    case_id = await _create_case(client, operator_headers, patient)
    await _capture_consent(client, operator_headers, case_id)
    call = await _create_call(
        client, operator_headers, case_id, "Caller reports chest pain and needs immediate help."
    )
    routed = await client.post(
        f"/api/v1/calls/{call['id']}/route", json={}, headers=operator_headers
    )
    assert routed.status_code == 200
    routed_task_id = routed.json()["task_id"]

    escalation = await client.post(
        f"/api/v1/calls/{call['id']}/escalate",
        json={"reason": "Immediate human handover"},
        headers=operator_headers,
    )
    assert escalation.status_code == 200
    body = escalation.json()
    assert body["call"]["status"] == "escalated"
    assert body["task_priority"] == "urgent"
    assert body["handover_context"]["transcript"] == call["transcript"]
    assert body["handover_context"]["phone_number"] == "0412345678"

    # Same task the route step created, now transitioned, not a new one.
    task = await client.get(f"/api/v1/tasks/{routed_task_id}", headers=operator_headers)
    assert task.status_code == 200
    assert task.json()["id"] == routed_task_id
    assert task.json()["call_id"] == call["id"]
    assert task.json()["status"] == "escalated"


async def test_call_escalation_prevents_duplicate_active_handover(
    client: AsyncClient, operator_headers: dict, patient: Patient, monkeypatch
):
    _mock_classifier(monkeypatch, "urgent_emergency", 0.95)
    case_id = await _create_case(client, operator_headers, patient)
    await _capture_consent(client, operator_headers, case_id)
    call = await _create_call(client, operator_headers, case_id, "Urgent chest pain.")
    await client.post(f"/api/v1/calls/{call['id']}/route", json={}, headers=operator_headers)

    first = await client.post(
        f"/api/v1/calls/{call['id']}/escalate", json={}, headers=operator_headers
    )
    second = await client.post(
        f"/api/v1/calls/{call['id']}/escalate", json={}, headers=operator_headers
    )

    assert first.status_code == 200
    assert second.status_code == 409


async def test_call_routing_and_escalation_require_manage_cases(
    client: AsyncClient, front_desk_headers: dict, patient: Patient
):
    case_id = await _create_case(client, front_desk_headers, patient)
    call = await _create_call(client, front_desk_headers, case_id, "Urgent request")

    route = await client.post(
        f"/api/v1/calls/{call['id']}/route", json={}, headers=front_desk_headers
    )
    escalate = await client.post(
        f"/api/v1/calls/{call['id']}/escalate", json={}, headers=front_desk_headers
    )

    assert route.status_code == 403
    assert escalate.status_code == 403
