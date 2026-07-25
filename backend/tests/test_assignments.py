import uuid

from httpx import AsyncClient

from app.models import Patient, User


async def test_create_assignment_allowed_for_admin(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    response = await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": str(patient.id)},
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["doctor_id"] == str(doctor_user.id)
    assert body["patient_id"] == str(patient.id)


async def test_create_assignment_denied_for_doctor(
    client: AsyncClient, doctor_headers: dict, doctor_user: User, patient: Patient
):
    response = await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": str(patient.id)},
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_create_assignment_duplicate_returns_409(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    payload = {"doctor_id": str(doctor_user.id), "patient_id": str(patient.id)}
    first = await client.post("/api/v1/assignments", json=payload, headers=admin_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/assignments", json=payload, headers=admin_headers)
    assert second.status_code == 409


async def test_create_assignment_missing_doctor_returns_404(
    client: AsyncClient, admin_headers: dict, patient: Patient
):
    response = await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(uuid.uuid4()), "patient_id": str(patient.id)},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_create_assignment_missing_patient_returns_404(
    client: AsyncClient, admin_headers: dict, doctor_user: User
):
    response = await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_create_assignment_non_doctor_target_returns_422(
    client: AsyncClient, admin_headers: dict, front_desk_user: User, patient: Patient
):
    response = await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(front_desk_user.id), "patient_id": str(patient.id)},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_delete_assignment_removes(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    payload = {"doctor_id": str(doctor_user.id), "patient_id": str(patient.id)}
    await client.post("/api/v1/assignments", json=payload, headers=admin_headers)

    response = await client.delete(
        f"/api/v1/assignments/{doctor_user.id}/{patient.id}", headers=admin_headers
    )
    assert response.status_code == 204

    listed = await client.get(
        "/api/v1/assignments", params={"doctor_id": str(doctor_user.id)}, headers=admin_headers
    )
    assert listed.json() == []


async def test_delete_assignment_missing_returns_404(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    response = await client.delete(
        f"/api/v1/assignments/{doctor_user.id}/{patient.id}", headers=admin_headers
    )
    assert response.status_code == 404


async def test_list_assignments_scoped_to_doctor(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    await client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor_user.id), "patient_id": str(patient.id)},
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/assignments", params={"doctor_id": str(doctor_user.id)}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["patient_id"] == str(patient.id)
