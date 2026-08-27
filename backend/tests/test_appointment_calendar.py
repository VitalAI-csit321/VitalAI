from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models import Patient, User
from app.models.user import UserRole
from tests.test_appointments import _create_case

pytestmark = pytest.mark.asyncio


async def _second_doctor(
    db_session: AsyncSession, email: str = "second-doctor@example.com"
) -> User:
    """A distinct DOCTOR user, for PATCH doctor_id reassignment tests."""
    doctor = User(
        email=email,
        hashed_password=hash_password("password123"),
        full_name="Second Doctor",
        role=UserRole.DOCTOR,
    )
    db_session.add(doctor)
    await db_session.commit()
    await db_session.refresh(doctor)
    return doctor


async def test_appointment_response_includes_derived_and_joined_fields(
    client, admin_headers, booked_appointment
):
    response = await client.get("/api/v1/appointments", headers=admin_headers)
    assert response.status_code == 200
    item = response.json()["items"][0]

    # Derived, never stored.
    assert item["end_time"] > item["time_slot"]
    assert item["duration_minutes"] == 30
    # Joined from users/patients, not columns on appointments.
    assert item["doctor_name"] is not None
    assert "reference_code" in item and item["reference_code"].startswith("APT-")


async def test_list_filters_by_date_range(client, admin_headers, booked_appointment):
    inside = await client.get(
        "/api/v1/appointments",
        headers=admin_headers,
        params={"date_from": "2026-09-01T00:00:00Z", "date_to": "2026-09-02T00:00:00Z"},
    )
    assert inside.json()["total"] == 1

    outside = await client.get(
        "/api/v1/appointments",
        headers=admin_headers,
        params={"date_from": "2026-10-01T00:00:00Z", "date_to": "2026-10-02T00:00:00Z"},
    )
    assert outside.json()["total"] == 0


async def test_list_filters_by_status(client, admin_headers, booked_appointment):
    confirmed = await client.get(
        "/api/v1/appointments", headers=admin_headers, params={"status": "confirmed"}
    )
    assert confirmed.json()["total"] == 1

    cancelled = await client.get(
        "/api/v1/appointments", headers=admin_headers, params={"status": "cancelled"}
    )
    assert cancelled.json()["total"] == 0


async def test_list_filters_by_appointment_type(client, admin_headers, booked_appointment):
    response = await client.get(
        "/api/v1/appointments", headers=admin_headers, params={"appointment_type": "procedure"}
    )
    assert response.json()["total"] == 0


async def test_calendar_month_groups_by_day_with_stats(client, admin_headers, booked_appointment):
    response = await client.get(
        "/api/v1/appointments/calendar", headers=admin_headers, params={"year": 2026, "month": 9}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026 and body["month"] == 9
    assert set(body["stats"]) == {
        "scheduled",
        "pending_confirmation",
        "confirmed_today",
        "cancellations",
    }
    day = next(d for d in body["days"] if d["date"] == "2026-09-01")
    assert day["total"] == 1
    assert day["appointments"][0]["id"] == booked_appointment["id"]


async def test_calendar_month_excludes_other_months(client, admin_headers, booked_appointment):
    response = await client.get(
        "/api/v1/appointments/calendar", headers=admin_headers, params={"year": 2026, "month": 10}
    )
    assert all(d["total"] == 0 for d in response.json()["days"])


async def test_calendar_markers_returns_only_days_with_appointments(
    client, admin_headers, booked_appointment
):
    response = await client.get(
        "/api/v1/appointments/calendar/markers",
        headers=admin_headers,
        params={"year": 2026, "month": 9},
    )
    assert response.status_code == 200
    assert response.json() == [{"date": "2026-09-01", "count": 1}]


async def test_day_view_reports_totals_and_providers(client, admin_headers, booked_appointment):
    response = await client.get(
        "/api/v1/appointments/day", headers=admin_headers, params={"date": "2026-09-01"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-09-01"
    assert body["total_booked_minutes"] == 30
    assert body["status_breakdown"]["confirmed"] == 1
    assert body["providers"][0]["appointment_count"] == 1
    assert body["providers"][0]["doctor_name"]


async def test_availability_marks_booked_slots_unavailable(
    client, admin_headers, seeded_doctor, booked_appointment
):
    response = await client.get(
        "/api/v1/appointments/availability",
        headers=admin_headers,
        params={"doctor_id": str(seeded_doctor.id), "date": "2026-09-01", "slot_minutes": 30},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slot_minutes"] == 30
    # 8am to 6pm in 30 minute slots.
    assert len(body["slots"]) == 20
    booked = next(s for s in body["slots"] if s["start"].startswith("2026-09-01T09:00"))
    assert booked["available"] is False
    free = next(s for s in body["slots"] if s["start"].startswith("2026-09-01T11:00"))
    assert free["available"] is True


async def test_availability_ignores_cancelled_appointments(
    client, admin_headers, seeded_doctor, booked_appointment
):
    await client.post(
        f"/api/v1/appointments/{booked_appointment['id']}/cancel",
        headers=admin_headers,
        json={"cancel_reason": "patient rescheduled"},
    )
    response = await client.get(
        "/api/v1/appointments/availability",
        headers=admin_headers,
        params={"doctor_id": str(seeded_doctor.id), "date": "2026-09-01"},
    )
    slot = next(s for s in response.json()["slots"] if s["start"].startswith("2026-09-01T09:00"))
    assert slot["available"] is True


async def test_availability_denies_doctor_for_other_doctors_calendar(
    client, doctor_headers, db_session: AsyncSession
):
    """I1: /availability now has the same own-calendar-only parity check as
    every other doctor-scoped endpoint.
    """
    other_doctor = await _second_doctor(db_session, "availability-other-doctor@example.com")
    response = await client.get(
        "/api/v1/appointments/availability",
        headers=doctor_headers,
        params={"doctor_id": str(other_doctor.id), "date": "2026-09-01"},
    )
    assert response.status_code == 403


async def test_appointment_detail_includes_patient_consent_and_history(
    client, admin_headers, booked_appointment
):
    response = await client.get(
        f"/api/v1/appointments/{booked_appointment['id']}", headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == booked_appointment["id"]
    assert "patient" in body and "consent" in body
    # The booking itself was audited, so history is never empty.
    assert any(h["action"] == "appointment.booked" for h in body["history"])


async def test_appointment_detail_404_for_unknown_id(client, admin_headers):
    response = await client.get(
        "/api/v1/appointments/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404


async def test_patch_updates_mutable_fields(client, admin_headers, booked_appointment):
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"duration_minutes": 45, "location": "Room 3", "appointment_type": "follow_up"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["duration_minutes"] == 45
    assert body["location"] == "Room 3"
    assert body["appointment_type"] == "follow_up"


async def test_patch_rejects_zero_duration(client, admin_headers, booked_appointment):
    """F4: rejected at the schema layer with 422, never reaching the DB."""
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"duration_minutes": 0},
    )
    assert response.status_code == 422


async def test_patch_rejects_negative_duration(client, admin_headers, booked_appointment):
    """F5: would raise DataError, not IntegrityError, if it reached the DB."""
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"duration_minutes": -30},
    )
    assert response.status_code == 422


async def test_repeat_creates_a_linked_series(
    client: AsyncClient, admin_headers: dict, seeded_doctor: User, patient: Patient
):
    case_id = await _create_case(client, admin_headers, patient)

    response = await client.post(
        "/api/v1/appointments",
        headers=admin_headers,
        json={
            "doctor_id": str(seeded_doctor.id),
            "case_id": case_id,
            "time_slot": "2026-11-02T09:00:00Z",
            "duration_minutes": 30,
            "repeat": {"interval_days": 7, "occurrences": 3},
        },
    )
    assert response.status_code == 201
    first = response.json()
    assert first["series_id"] is not None

    listed = await client.get(
        "/api/v1/appointments",
        headers=admin_headers,
        params={"date_from": "2026-11-01T00:00:00Z", "date_to": "2026-11-30T00:00:00Z"},
    )
    series = [a for a in listed.json()["items"] if a["series_id"] == first["series_id"]]
    assert len(series) == 3
    assert sorted(a["time_slot"][:10] for a in series) == ["2026-11-02", "2026-11-09", "2026-11-16"]


async def test_single_booking_has_no_series_id(client, admin_headers, booked_appointment):
    assert booked_appointment["series_id"] is None


async def test_repeat_series_collision_leaves_no_partial_series(
    pg_client: AsyncClient, pg_admin_headers: dict, pg_doctor_user: User, pg_patient: Patient
):
    """Verify series atomicity: if any occurrence collides, nothing is booked.

    When DB constraint (Postgres EXCLUDE) detects a collision during flush,
    IntegrityError is caught and the entire series transaction rolls back.

    C1: forced onto real Postgres (pg_client/pg_session) unconditionally, so
    this always exercises migration 0026's EXCLUDE USING gist constraint
    regardless of what DATABASE_URL the rest of the suite runs under. That
    constraint has no SQLite equivalent, so the old SQLite branch (series
    always succeeds, nothing to assert about collisions) is gone -- this test
    now only has one path to verify.
    """
    case_id = await _create_case(pg_client, pg_admin_headers, pg_patient)

    # Create a standalone appointment at a specific time slot.
    collision_slot = "2026-11-09T10:00:00Z"
    standalone = await pg_client.post(
        "/api/v1/appointments",
        headers=pg_admin_headers,
        json={
            "doctor_id": str(pg_doctor_user.id),
            "case_id": case_id,
            "time_slot": collision_slot,
            "duration_minutes": 30,
        },
    )
    assert standalone.status_code == 201
    standalone_id = standalone.json()["id"]

    # Attempt to book a series where occurrence 2 collides with the standalone appointment.
    # Occurrence 1: 2026-11-02T10:00:00Z (free)
    # Occurrence 2: 2026-11-09T10:00:00Z (collision!)
    # Occurrence 3: 2026-11-16T10:00:00Z (free)
    response = await pg_client.post(
        "/api/v1/appointments",
        headers=pg_admin_headers,
        json={
            "doctor_id": str(pg_doctor_user.id),
            "case_id": case_id,
            "time_slot": "2026-11-02T10:00:00Z",
            "duration_minutes": 30,
            "repeat": {"interval_days": 7, "occurrences": 3},
        },
    )

    assert response.status_code == 409
    listed = await pg_client.get(
        "/api/v1/appointments",
        headers=pg_admin_headers,
        params={"date_from": "2026-11-01T00:00:00Z", "date_to": "2026-11-30T00:00:00Z"},
    )
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == standalone_id


async def test_complete_marks_appointment_completed(client, admin_headers, booked_appointment):
    response = await client.post(
        f"/api/v1/appointments/{booked_appointment['id']}/complete", headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


async def test_cancel_accepts_a_reason(client, admin_headers, booked_appointment):
    response = await client.post(
        f"/api/v1/appointments/{booked_appointment['id']}/cancel",
        headers=admin_headers,
        json={"cancel_reason": "patient unwell", "notify_patient": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_patch_status_pending_to_confirmed_succeeds(
    client: AsyncClient, admin_headers: dict, doctor_user: User, patient: Patient
):
    """C2: status is no longer silently dropped -- the Edit page's own
    pending<->confirmed transition must actually apply.
    """
    case_id = await _create_case(client, admin_headers, patient)
    created = await client.post(
        "/api/v1/appointments",
        headers=admin_headers,
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": case_id,
            "time_slot": "2026-09-05T09:00:00Z",
            "duration_minutes": 30,
            "status": "pending",
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"

    response = await client.patch(
        f"/api/v1/appointments/{created.json()['id']}",
        headers=admin_headers,
        json={"status": "confirmed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


async def test_patch_rejects_terminal_status_transition(client, admin_headers, booked_appointment):
    """C2: PATCH still cannot bounce status straight to a terminal state --
    that must go through the dedicated /complete or /cancel endpoint -- but
    now it's a clear 409 instead of a silent no-op.
    """
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"status": "completed"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "/complete" in detail or "/cancel" in detail


async def test_patch_reassigns_to_valid_doctor(
    client: AsyncClient, admin_headers: dict, booked_appointment, db_session: AsyncSession
):
    """C2: a valid doctor_id on PATCH is validated and applied, not dropped."""
    second_doctor = await _second_doctor(db_session, "patch-reassign-target@example.com")

    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"doctor_id": str(second_doctor.id)},
    )
    assert response.status_code == 200
    assert response.json()["doctor_id"] == str(second_doctor.id)


async def test_patch_rejects_unknown_doctor_id(client, admin_headers, booked_appointment):
    """C2: an unknown doctor_id on PATCH is now validated, mirroring POST."""
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"doctor_id": str(uuid4())},
    )
    assert response.status_code == 404


async def test_patch_rejects_completed_appointment(client, admin_headers, booked_appointment):
    """Verify PATCH cannot edit a completed appointment."""
    await client.post(
        f"/api/v1/appointments/{booked_appointment['id']}/complete", headers=admin_headers
    )
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=admin_headers,
        json={"duration_minutes": 60},
    )
    assert response.status_code == 409
