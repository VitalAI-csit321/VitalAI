import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Patient, User
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord


async def _create_case(client: AsyncClient, headers: dict, patient: Patient) -> str:
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_id": str(patient.id),
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=headers,
    )
    return response.json()["id"]


async def test_consent_capture_flow(client: AsyncClient, admin_headers: dict, patient: Patient):
    case_id = await _create_case(client, admin_headers, patient)

    create = await client.post(
        "/api/v1/consent",
        json={"case_id": case_id},
        headers=admin_headers,
    )
    assert create.status_code == 201
    consent_id = create.json()["id"]
    assert create.json()["status"] == "pending"

    capture = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert capture.status_code == 200
    assert capture.json()["status"] == "captured"
    assert capture.json()["captured_at"] is not None


async def test_consent_capture_twice_returns_409(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    first = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert first.status_code == 200

    second = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert second.status_code == 409


async def test_consent_withdraw_after_capture(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    withdraw = await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)
    assert withdraw.status_code == 200
    assert withdraw.json()["status"] == "withdrawn"


async def test_consent_withdraw_then_capture_blocked(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)
    capture = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert capture.status_code == 409


async def test_consent_capture_not_found_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.post(f"/api/v1/consent/{uuid.uuid4()}/capture", headers=admin_headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_consent_withdraw_not_found_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.post(f"/api/v1/consent/{uuid.uuid4()}/withdraw", headers=admin_headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_consent_withdraw_twice_returns_409(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    first = await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)
    assert first.status_code == 200

    second = await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)
    assert second.status_code == 409
    assert "withdraw" in second.json()["detail"].lower()


async def test_consent_create_allowed_for_front_desk(
    client: AsyncClient, admin_headers: dict, front_desk_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/consent", json={"case_id": case_id}, headers=front_desk_headers
    )
    assert response.status_code == 201


async def test_consent_create_denied_for_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/consent", json={"case_id": case_id}, headers=doctor_headers
    )
    assert response.status_code == 403


async def test_consent_by_case_allowed_for_assigned_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_headers: dict,
    doctor_user: User,
    patient: Patient,
):
    """DOCTOR has VIEW_RECORDS_GENERAL, scoped to assigned patients (RBAC report §6)."""
    case_id = await _create_case(client, admin_headers, patient)
    await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": str(patient.id)},
        headers=admin_headers,
    )

    response = await client.get(f"/api/v1/consent/by-case/{case_id}", headers=doctor_headers)
    assert response.status_code == 200


async def test_consent_by_case_denied_for_unassigned_doctor(
    client: AsyncClient, admin_headers: dict, doctor_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)

    response = await client.get(f"/api/v1/consent/by-case/{case_id}", headers=doctor_headers)
    assert response.status_code == 404


async def test_consent_by_case_allowed_for_operator_without_assignment(
    client: AsyncClient, admin_headers: dict, operator_headers: dict, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)

    response = await client.get(f"/api/v1/consent/by-case/{case_id}", headers=operator_headers)
    assert response.status_code == 200


async def test_consent_by_case_denied_for_doctor_on_unlinked_legacy_case(
    client: AsyncClient, doctor_headers: dict, db_session: AsyncSession
):
    """A pre-Phase-2 case with no patient_id can't be checked against a
    doctor's assignment set, so it fails closed (RBAC report §6/§7)."""
    case = IntakeCase(
        patient_id=None,
        patient_name="Legacy Free-Text Patient",
        contact_reason="Legacy visit",
        contact_channel="phone",
    )
    db_session.add(case)
    await db_session.flush()
    db_session.add(ConsentRecord(case_id=case.id))
    await db_session.commit()

    response = await client.get(f"/api/v1/consent/by-case/{case.id}", headers=doctor_headers)
    assert response.status_code == 404
