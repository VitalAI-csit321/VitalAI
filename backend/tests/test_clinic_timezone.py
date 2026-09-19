"""The clinic runs in a timezone, not in UTC (build spec section 10.0).

`time_slot` stays UTC-aware in the database. What changes is interpretation:
`settings.clinic_open_hour` is an hour in `settings.clinic_timezone`, and an
appointment belongs to the clinic-local day it happens on, not to whatever
day it happens to fall on in UTC.

The timezone itself is read-only in the settings registry. A name that is not
a real zone would raise inside zoneinfo on every calendar call, so it is not
something an API write may set.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.services import settings_service

pytestmark = pytest.mark.asyncio

SYDNEY = ZoneInfo("Australia/Sydney")
# A Tuesday in September: Sydney is on AEST (UTC+10), no DST transition near it.
DAY = "2026-09-01"


def _local(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(SYDNEY)


async def _book(client, headers, doctor, case, when: str, minutes: int = 30):
    response = await client.post(
        "/api/v1/appointments",
        headers=headers,
        json={
            "doctor_id": str(doctor.id),
            "case_id": str(case.id),
            "time_slot": when,
            "duration_minutes": minutes,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _availability(client, headers, doctor, day: str = DAY):
    response = await client.get(
        "/api/v1/appointments/availability",
        headers=headers,
        params={"doctor_id": str(doctor.id), "date": day, "slot_minutes": 30},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- the setting itself ----------------------------------------------------------------


def test_clinic_timezone_is_registered_read_only():
    spec = settings_service.SETTINGS_REGISTRY["clinic_timezone"]
    assert spec.type is str
    assert spec.group == "General"
    assert spec.editable is False
    assert ZoneInfo(settings.clinic_timezone)


def test_the_api_refuses_to_write_the_clinic_timezone():
    with pytest.raises(settings_service.SettingsValidationError, match="read-only"):
        settings_service.validate({"clinic_timezone": "Europe/Paris"})


def test_the_clinic_hours_say_they_are_local_time():
    for key in ("clinic_open_hour", "clinic_close_hour"):
        assert "local" in settings_service.SETTINGS_REGISTRY[key].help.lower()


# --- availability ----------------------------------------------------------------------


async def test_the_first_slot_of_a_day_is_the_opening_hour_in_clinic_local_time(
    client, admin_headers, seeded_doctor, monkeypatch
):
    """Gate (b). With clinic_open_hour 8 the day starts at 08:00 Sydney, which
    is 22:00 UTC the day before, not 08:00 UTC."""
    monkeypatch.setattr(settings, "clinic_open_hour", 8)
    monkeypatch.setattr(settings, "clinic_close_hour", 18)

    body = await _availability(client, admin_headers, seeded_doctor)

    first, last = _local(body["slots"][0]["start"]), _local(body["slots"][-1]["end"])
    assert (first.hour, first.minute, first.date().isoformat()) == (8, 0, DAY)
    assert (last.hour, last.minute, last.date().isoformat()) == (18, 0, DAY)
    # The same instant, said in UTC, so a re-introduced tzinfo=UTC cannot pass.
    assert datetime.fromisoformat(body["slots"][0]["start"]).astimezone(UTC) == datetime(
        2026, 8, 31, 22, 0, tzinfo=UTC
    )
    assert len(body["slots"]) == 20


async def test_an_appointment_in_the_clinic_morning_blocks_its_slot(
    client, admin_headers, seeded_doctor, seeded_case
):
    """09:00 Sydney on 2026-09-01 is 23:00 UTC on 2026-08-31, so a busy-slot
    window built on the UTC day never sees it."""
    await _book(client, admin_headers, seeded_doctor, seeded_case, "2026-08-31T23:00:00Z")

    body = await _availability(client, admin_headers, seeded_doctor)

    booked = next(s for s in body["slots"] if _local(s["start"]).hour == 9)
    assert booked["available"] is False
    free = next(s for s in body["slots"] if _local(s["start"]).hour == 11)
    assert free["available"] is True
