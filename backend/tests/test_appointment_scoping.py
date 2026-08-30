"""A doctor may only see appointments for patients assigned to them.

Every endpoint added in Plan 2 must inherit PR #16's row scoping. A gap here
leaks one patient's schedule to an unrelated doctor.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_list_excludes_unassigned_patients(
    client, unassigned_doctor_headers, booked_appointment
):
    response = await client.get("/api/v1/appointments", headers=unassigned_doctor_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_calendar_excludes_unassigned_patients(
    client, unassigned_doctor_headers, booked_appointment
):
    response = await client.get(
        "/api/v1/appointments/calendar",
        headers=unassigned_doctor_headers,
        params={"year": 2026, "month": 9},
    )
    assert response.status_code == 200
    assert all(day["total"] == 0 for day in response.json()["days"])


async def test_markers_exclude_unassigned_patients(
    client, unassigned_doctor_headers, booked_appointment
):
    response = await client.get(
        "/api/v1/appointments/calendar/markers",
        headers=unassigned_doctor_headers,
        params={"year": 2026, "month": 9},
    )
    assert response.json() == []


async def test_day_view_excludes_unassigned_patients(
    client, unassigned_doctor_headers, booked_appointment
):
    response = await client.get(
        "/api/v1/appointments/day",
        headers=unassigned_doctor_headers,
        params={"date": "2026-09-01"},
    )
    assert response.json()["total_booked_minutes"] == 0


async def test_detail_404s_for_unassigned_doctor(
    client, unassigned_doctor_headers, booked_appointment
):
    """404 rather than 403: an unassigned doctor must not learn the id exists."""
    response = await client.get(
        f"/api/v1/appointments/{booked_appointment['id']}", headers=unassigned_doctor_headers
    )
    assert response.status_code == 404


async def test_patch_404s_for_unassigned_doctor(
    client, unassigned_doctor_headers, booked_appointment
):
    response = await client.patch(
        f"/api/v1/appointments/{booked_appointment['id']}",
        headers=unassigned_doctor_headers,
        json={"location": "should not apply"},
    )
    assert response.status_code == 404


async def test_complete_404s_for_unassigned_doctor(
    client, unassigned_doctor_headers, booked_appointment
):
    response = await client.post(
        f"/api/v1/appointments/{booked_appointment['id']}/complete",
        headers=unassigned_doctor_headers,
    )
    assert response.status_code == 404


async def test_assigned_doctor_can_see_their_own_appointment(
    client, assigned_doctor_headers, booked_appointment
):
    """The mirror case: scoping must not lock out the doctor who owns it."""
    response = await client.get(
        f"/api/v1/appointments/{booked_appointment['id']}", headers=assigned_doctor_headers
    )
    assert response.status_code == 200
