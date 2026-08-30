from datetime import date

from scripts.ingest_appointment_history import ParsedVisit, parse_history

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
