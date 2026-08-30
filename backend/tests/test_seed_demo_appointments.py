"""The slot-planning half of the seed is pure, so it is unit-testable
without a database. The DB-writing half is exercised in Task 5's run.
"""

from datetime import UTC, datetime
from uuid import uuid4

from scripts.seed_demo_appointments import build_demo_appointments

_MONTH = datetime(2026, 9, 1, tzinfo=UTC)


def test_plan_is_deterministic_for_the_same_inputs():
    patients = [uuid4() for _ in range(5)]
    doctors = [uuid4() for _ in range(2)]
    first = build_demo_appointments(patients, doctors, _MONTH)
    second = build_demo_appointments(patients, doctors, _MONTH)
    assert first == second


def test_all_slots_are_inside_clinic_hours_on_weekdays():
    plan = build_demo_appointments([uuid4() for _ in range(10)], [uuid4()], _MONTH)
    for row in plan:
        assert 8 <= row["time_slot"].hour < 18
        assert row["time_slot"].weekday() < 5


def test_no_two_appointments_share_a_doctor_and_time():
    """The exclusion constraint would reject the seed otherwise."""
    plan = build_demo_appointments([uuid4() for _ in range(40)], [uuid4(), uuid4()], _MONTH)
    seen = {(row["doctor_id"], row["time_slot"]) for row in plan}
    assert len(seen) == len(plan)


def test_every_slot_lands_in_the_requested_month():
    plan = build_demo_appointments([uuid4() for _ in range(20)], [uuid4()], _MONTH)
    assert all(row["time_slot"].month == 9 and row["time_slot"].year == 2026 for row in plan)


def test_statuses_are_realistic_and_never_ai_confirmed():
    plan = build_demo_appointments([uuid4() for _ in range(30)], [uuid4()], _MONTH)
    statuses = {row["status"] for row in plan}
    assert statuses <= {"confirmed", "completed", "cancelled", "pending"}
