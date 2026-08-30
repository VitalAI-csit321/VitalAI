import pytest

pytestmark = pytest.mark.asyncio


async def test_suggestions_are_pending_never_confirmed(
    client, admin_headers, seeded_doctor, seeded_case
):
    """RBAC invariant 2: AI never commits an appointment."""
    response = await client.post(
        "/api/v1/appointments/suggest",
        headers=admin_headers,
        json={
            "case_id": str(seeded_case.id),
            "doctor_id": str(seeded_doctor.id),
            "from_date": "2026-09-07",
            "count": 3,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body) == 3
    assert all(item["status"] == "pending" for item in body)


async def test_suggestions_may_overlap_each_other(
    client, admin_headers, seeded_doctor, seeded_case
):
    """ADR-003: pending rows are advisory and do not reserve the slot, so a
    second suggestion round must not fail."""
    payload = {
        "case_id": str(seeded_case.id),
        "doctor_id": str(seeded_doctor.id),
        "from_date": "2026-09-07",
        "count": 2,
    }
    first = await client.post("/api/v1/appointments/suggest", headers=admin_headers, json=payload)
    second = await client.post("/api/v1/appointments/suggest", headers=admin_headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201


async def test_suggestions_avoid_slots_already_confirmed(
    client, admin_headers, seeded_doctor, seeded_case
):
    booked = await client.post(
        "/api/v1/appointments",
        headers=admin_headers,
        json={
            "doctor_id": str(seeded_doctor.id),
            "case_id": str(seeded_case.id),
            "time_slot": "2026-09-07T08:00:00Z",
            "duration_minutes": 30,
        },
    )
    assert booked.status_code == 201

    response = await client.post(
        "/api/v1/appointments/suggest",
        headers=admin_headers,
        json={
            "case_id": str(seeded_case.id),
            "doctor_id": str(seeded_doctor.id),
            "from_date": "2026-09-07",
            "count": 1,
        },
    )
    assert response.json()[0]["time_slot"] != "2026-09-07T08:00:00Z"


async def test_confirming_a_suggestion_uses_the_normal_patch_path(
    client, admin_headers, seeded_doctor, seeded_case
):
    """A human accepts by PATCHing to confirmed. That is the only way a
    suggestion becomes a real booking."""
    suggested = (
        await client.post(
            "/api/v1/appointments/suggest",
            headers=admin_headers,
            json={
                "case_id": str(seeded_case.id),
                "doctor_id": str(seeded_doctor.id),
                "from_date": "2026-09-08",
                "count": 1,
            },
        )
    ).json()[0]

    accepted = await client.patch(
        f"/api/v1/appointments/{suggested['id']}",
        headers=admin_headers,
        json={"status": "confirmed"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "confirmed"
