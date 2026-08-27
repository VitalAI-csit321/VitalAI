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
