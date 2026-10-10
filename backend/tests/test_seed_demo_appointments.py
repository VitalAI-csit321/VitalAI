"""The slot-planning half of the seed is pure, so it is unit-testable
without a database. The DB-writing half is exercised in Task 5's run.
"""

from datetime import date
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.services.appointment_service import is_clinic_day
from scripts.seed_demo_appointments import build_demo_appointments

_MONTH = date(2026, 9, 1)
SYDNEY = ZoneInfo("Australia/Sydney")


def _clinic(doctors: int, patients_each: int) -> dict:
    return {uuid4(): [uuid4() for _ in range(patients_each)] for _ in range(doctors)}


def test_plan_is_deterministic_for_the_same_inputs():
    clinic = _clinic(2, 5)
    assert build_demo_appointments(clinic, _MONTH) == build_demo_appointments(clinic, _MONTH)


def test_each_patient_is_booked_only_with_their_own_doctor():
    """The plan once dealt any patient to any doctor, so the calendar showed
    patients with doctors their records never mention."""
    clinic = _clinic(3, 6)
    plan = build_demo_appointments(clinic, _MONTH)
    assert plan
    assert all(row["patient_id"] in clinic[row["doctor_id"]] for row in plan)


def test_a_doctor_with_no_patients_gets_no_appointments():
    busy, new = uuid4(), uuid4()
    plan = build_demo_appointments({busy: [uuid4()], new: []}, _MONTH)
    assert {row["doctor_id"] for row in plan} == {busy}


def test_no_patient_is_in_more_than_about_once_a_week():
    plan = build_demo_appointments(_clinic(1, 3), _MONTH)
    visits: dict = {}
    for row in plan:
        visits[row["patient_id"]] = visits.get(row["patient_id"], 0) + 1
    assert max(visits.values()) <= 4


def test_all_slots_are_inside_clinic_hours_on_clinic_days_in_clinic_time():
    """The seed once planned 8 to 18 in UTC, which is evening and night at the
    clinic, so the hour is read on the clinic's clock, not the stored one."""
    plan = build_demo_appointments(_clinic(1, 10), _MONTH)
    assert plan
    for row in plan:
        local = row["time_slot"].astimezone(SYDNEY)
        assert 8 <= local.hour < 18
        assert is_clinic_day(local.date())


def test_a_public_holiday_gets_no_appointments():
    """Monday 5 October 2026 is Labour Day in NSW: a weekday the clinic is shut."""
    plan = build_demo_appointments(_clinic(1, 60), date(2026, 10, 1))
    days = {row["time_slot"].astimezone(SYDNEY).date() for row in plan}
    assert date(2026, 10, 6) in days
    assert date(2026, 10, 5) not in days


def test_no_two_appointments_share_a_doctor_and_time():
    """The exclusion constraint would reject the seed otherwise."""
    plan = build_demo_appointments(_clinic(2, 40), _MONTH)
    seen = {(row["doctor_id"], row["time_slot"]) for row in plan}
    assert len(seen) == len(plan)


def test_every_slot_lands_in_the_requested_month():
    plan = build_demo_appointments(_clinic(1, 20), _MONTH)
    local = [row["time_slot"].astimezone(SYDNEY) for row in plan]
    assert all(slot.month == 9 and slot.year == 2026 for slot in local)


def test_statuses_are_realistic_and_never_ai_confirmed():
    plan = build_demo_appointments(_clinic(1, 30), _MONTH)
    statuses = {row["status"] for row in plan}
    assert statuses <= {"confirmed", "completed", "cancelled", "pending"}
