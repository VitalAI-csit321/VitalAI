from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.models.user import User, UserRole
from scripts.ingest_appointment_history import (
    ParsedVisit,
    apply_roster,
    clinic_roster,
    doctor_user_id,
    parse_history,
    visit_slot,
)

_SAMPLE = """Appointment History

Patient: Vickie Wise

09/12/2024 - General Consultation - Dr Marcus O'Connell
06/12/2025 - Specialist Referral - Dr Marcus O'Connell
31/07/2026 - Specialist Referral - Dr Marcus O'Connell
"""


def test_parses_every_visit_line():
    visits = parse_history(_SAMPLE)
    assert len(visits) == 3
    assert visits[0] == ParsedVisit(
        visit_date=date(2024, 12, 9),
        visit_type="General Consultation",
        doctor_name="Dr Marcus O'Connell",
    )


def test_parses_day_first_dates_not_month_first():
    """09/12/2024 is 9 December, not 12 September. Getting this backwards
    silently shifts a patient's whole history."""
    visits = parse_history("01/02/2025 - General Consultation - Dr A B")
    assert visits[0].visit_date == date(2025, 2, 1)


def test_ignores_headers_and_blank_lines():
    assert parse_history("Appointment History\n\nPatient: X\n\n") == []


def test_ignores_malformed_lines_without_raising():
    visits = parse_history("not a visit line\n09/12/2024 - Consult - Dr A\ngarbage - - -")
    assert len(visits) == 1


def test_handles_apostrophes_and_hyphens_in_doctor_names():
    visits = parse_history("09/12/2024 - Follow-Up Visit - Dr Mary-Jane O'Neill")
    assert visits[0].doctor_name == "Dr Mary-Jane O'Neill"
    assert visits[0].visit_type == "Follow-Up Visit"


@pytest.mark.asyncio
async def test_a_roster_doctor_gets_one_account_however_often_the_seed_runs(db_session):
    """The roster-only doctors have no corpus visits to create them, and a
    second seed run must find the account, not add a twin."""
    name = "Dr Elena Kowalski"
    first = await doctor_user_id(db_session, name)
    second = await doctor_user_id(db_session, name)

    assert first == second
    doctor = await db_session.get(User, first)
    assert (doctor.full_name, doctor.role) == (name, UserRole.DOCTOR)
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.full_name == name)
    )
    assert count == 1


def test_a_visit_is_filed_at_nine_on_the_clinic_clock_not_in_utc():
    """9am UTC is 7pm or 8pm in Sydney. The stored instant is 9am Sydney, which
    is the evening before in UTC, an hour apart between summer and winter."""
    assert visit_slot(date(2026, 1, 15), 0) == datetime(2026, 1, 14, 22, 0, tzinfo=UTC)
    assert visit_slot(date(2026, 7, 15), 0) == datetime(2026, 7, 14, 23, 0, tzinfo=UTC)
    assert visit_slot(date(2026, 7, 15), 2) == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)


def test_the_roster_is_read_from_the_table_patients_are_quoted_from():
    roster = clinic_roster()
    assert len(roster) == 8
    assert roster["Dr Rohan Iyer"] == "Travel medicine and minor procedures"
    assert roster["Dr Aisha Rahman"] == "Women's health and antenatal care"


@pytest.mark.asyncio
async def test_every_roster_doctor_gets_an_account_with_their_special_interest(db_session):
    """Two roster doctors have no corpus visits, so only this creates them. An
    interest an admin has set since is not overwritten by a later seed."""
    await apply_roster(db_session)
    doctors = (await db_session.scalars(select(User).where(User.role == UserRole.DOCTOR))).all()
    assert {d.full_name: d.department for d in doctors} == clinic_roster()

    edited = next(d for d in doctors if d.full_name == "Dr Rohan Iyer")
    edited.department = "Travel medicine"
    await apply_roster(db_session)
    assert edited.department == "Travel medicine"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 8
