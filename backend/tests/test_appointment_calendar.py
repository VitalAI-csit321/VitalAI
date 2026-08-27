import pytest

pytestmark = pytest.mark.asyncio


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
