import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password
from app.models import Patient, User
from app.models.user import UserRole


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


def _slot(offset_days: int = 1) -> str:
    return (datetime.now(UTC).replace(microsecond=0) + timedelta(days=offset_days)).isoformat()


def _same_instant(a: str, b: str) -> bool:
    # SQLite (this suite's default DB) doesn't persist tzinfo on DateTime
    # columns, so a round-tripped value comes back naive even though the
    # wall-clock value is unchanged; compare with tzinfo stripped from both.
    return datetime.fromisoformat(a).replace(tzinfo=None) == datetime.fromisoformat(b).replace(
        tzinfo=None
    )


async def test_book_appointment_allowed_for_admin(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)

    response = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot()},
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["doctor_id"] == str(doctor_user.id)
    assert body["status"] == "confirmed"


async def test_book_appointment_allowed_for_own_calendar_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    await client.post(
        "/api/v1/assignments",
        json={
            "doctor_id": str(doctor_user.id),
            "patient_id": str(patient.id),
        },
        headers=admin_headers,
    )
    case_id = await _create_case(client, admin_headers, patient)

    response = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot()},
        headers=doctor_headers,
    )
    assert response.status_code == 201


async def test_book_appointment_denied_for_unassigned_patient(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": case_id,
            "time_slot": _slot(),
        },
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_book_appointment_denied_for_other_doctors_calendar(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    case_id = await _create_case(client, admin_headers, patient)
    other_doctor = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other-doc@example.com",
            "password": "TestPass123!",
            "full_name": "Other Doc",
        },
    )
    other_doctor_id = other_doctor.json()["id"]

    response = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": other_doctor_id, "case_id": case_id, "time_slot": _slot()},
        headers=doctor_headers,
    )
    assert response.status_code == 403


async def test_book_appointment_denied_for_front_desk_without_doctor_target(
    client: AsyncClient, front_desk_headers: dict
):
    """front_desk holds MANAGE_APPOINTMENTS_ALL, still 404s on a nonexistent doctor_id."""
    response = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(uuid.uuid4()), "case_id": str(uuid.uuid4()), "time_slot": _slot()},
        headers=front_desk_headers,
    )
    assert response.status_code == 404


async def test_book_appointment_non_doctor_target_returns_422(
    client: AsyncClient, admin_headers: dict, front_desk_user: User, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(front_desk_user.id), "case_id": case_id, "time_slot": _slot()},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_book_appointment_duplicate_slot_returns_409(
    pg_client: AsyncClient, pg_admin_headers: dict, pg_doctor_user: User, pg_patient: Patient
):
    """C1: forced onto real Postgres (pg_client/pg_session) so this always
    exercises migration 0026's EXCLUDE USING gist constraint, regardless of
    what DATABASE_URL the rest of the suite runs under. On the default
    SQLite backend there is no equivalent constraint, so this would silently
    stop testing anything.
    """
    case_id = await _create_case(pg_client, pg_admin_headers, pg_patient)
    slot = _slot()
    payload = {"doctor_id": str(pg_doctor_user.id), "case_id": case_id, "time_slot": slot}

    first = await pg_client.post("/api/v1/appointments", json=payload, headers=pg_admin_headers)
    assert first.status_code == 201

    second = await pg_client.post("/api/v1/appointments", json=payload, headers=pg_admin_headers)
    assert second.status_code == 409


async def test_list_appointments_scoped_to_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    await client.post(
        "/api/v1/assignments",
        json={
            "doctor_id": str(doctor_user.id),
            "patient_id": str(patient.id),
        },
        headers=admin_headers,
    )
    case_id = await _create_case(client, admin_headers, patient)
    await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )

    response = await client.get("/api/v1/appointments", headers=doctor_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["doctor_id"] == str(doctor_user.id)


async def test_list_appointments_hides_unassigned_patient(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    case_id = await _create_case(client, admin_headers, patient)

    created = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": case_id,
            "time_slot": _slot(1),
        },
        headers=admin_headers,
    )
    assert created.status_code == 201

    response = await client.get(
        "/api/v1/appointments",
        headers=doctor_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_list_appointments_unscoped_for_admin_with_doctor_filter(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    patient: Patient,
):
    case_id = await _create_case(client, admin_headers, patient)
    await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )

    response = await client.get(
        "/api/v1/appointments", params={"doctor_id": str(doctor_user.id)}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1

    unfiltered = await client.get("/api/v1/appointments", headers=admin_headers)
    assert unfiltered.status_code == 200
    assert unfiltered.json()["total"] >= 1


async def test_reschedule_appointment_allowed_for_owner_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    await client.post(
        "/api/v1/assignments",
        json={
            "doctor_id": str(doctor_user.id),
            "patient_id": str(patient.id),
        },
        headers=admin_headers,
    )
    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )
    appointment_id = created.json()["id"]
    new_slot = _slot(3)

    response = await client.post(
        f"/api/v1/appointments/{appointment_id}/reschedule",
        json={"time_slot": new_slot},
        headers=doctor_headers,
    )
    assert response.status_code == 200
    assert _same_instant(response.json()["time_slot"], new_slot)


async def _other_doctor_headers(db_session: AsyncSession, email: str) -> dict:
    other_doctor = User(
        email=email,
        hashed_password=hash_password("password123"),
        full_name="Other Doctor",
        role=UserRole.DOCTOR,
    )
    db_session.add(other_doctor)
    await db_session.commit()
    await db_session.refresh(other_doctor)
    return {"Authorization": f"Bearer {create_access_token(other_doctor.id, other_doctor.role)}"}


async def test_reschedule_appointment_denied_for_non_owner_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    patient: Patient,
    db_session: AsyncSession,
):
    other_doctor_headers = await _other_doctor_headers(
        db_session, "other-reschedule-check@example.com"
    )

    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )
    appointment_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/appointments/{appointment_id}/reschedule",
        json={"time_slot": _slot(3)},
        headers=other_doctor_headers,
    )
    assert response.status_code == 404


async def test_reschedule_appointment_denied_for_unassigned_patient(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": case_id,
            "time_slot": _slot(1),
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    appointment_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/appointments/{appointment_id}/reschedule",
        json={"time_slot": _slot(3)},
        headers=doctor_headers,
    )

    assert response.status_code == 404


async def test_cancel_appointment_denied_for_non_owner_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    patient: Patient,
    db_session: AsyncSession,
):
    other_doctor_headers = await _other_doctor_headers(db_session, "other-cancel-check@example.com")

    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )
    appointment_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/appointments/{appointment_id}/cancel", headers=other_doctor_headers
    )
    assert response.status_code == 404


async def test_cancel_appointment_denied_for_unassigned_patient(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    case_id = await _create_case(client, admin_headers, patient)

    created = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": case_id,
            "time_slot": _slot(1),
        },
        headers=admin_headers,
    )
    appointment_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/appointments/{appointment_id}/cancel",
        headers=doctor_headers,
    )

    assert response.status_code == 404


async def test_reschedule_missing_appointment_returns_404(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        f"/api/v1/appointments/{uuid.uuid4()}/reschedule",
        json={"time_slot": _slot()},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_cancel_appointment_allowed_for_owner_doctor(
    client: AsyncClient,
    admin_headers: dict,
    doctor_user: User,
    doctor_headers: dict,
    patient: Patient,
):
    await client.post(
        "/api/v1/assignments",
        json={
            "doctor_id": str(doctor_user.id),
            "patient_id": str(patient.id),
        },
        headers=admin_headers,
    )
    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )
    appointment_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/appointments/{appointment_id}/cancel", headers=doctor_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_cancel_appointment_twice_returns_409(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": str(doctor_user.id), "case_id": case_id, "time_slot": _slot(1)},
        headers=admin_headers,
    )
    appointment_id = created.json()["id"]

    first = await client.post(
        f"/api/v1/appointments/{appointment_id}/cancel", headers=admin_headers
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/appointments/{appointment_id}/cancel", headers=admin_headers
    )
    assert second.status_code == 409


async def test_appointments_denied_without_permission(client: AsyncClient):
    response = await client.get("/api/v1/appointments")
    assert response.status_code == 401


async def test_book_appointment_completed_status_returns_422(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    """I3: POST cannot create straight into completed/cancelled -- those bypass
    complete_appointment's CONFIRMED-only guard and (for cancelled) the
    overlap constraint entirely.
    """
    case_id = await _create_case(client, admin_headers, patient)
    response = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": case_id,
            "time_slot": _slot(),
            "status": "completed",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
