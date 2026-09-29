"""clinic_is_open: Mon-Fri 08:00-18:00 clinic time, public holidays closed (spec D3, D10)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.services.voicemail_service import clinic_is_open

SYDNEY = ZoneInfo("Australia/Sydney")


@pytest.fixture(autouse=True)
def clinic(monkeypatch):
    monkeypatch.setattr(settings, "clinic_open_hour", 8)
    monkeypatch.setattr(settings, "clinic_close_hour", 18)
    monkeypatch.setattr(settings, "clinic_timezone", "Australia/Sydney")
    monkeypatch.setattr(settings, "clinic_holiday_region", "NSW")


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        (datetime(2026, 9, 28, 7, 59), False),  # Monday, before opening
        (datetime(2026, 9, 28, 8, 0), True),
        (datetime(2026, 9, 28, 17, 59), True),
        (datetime(2026, 9, 28, 18, 0), False),
        (datetime(2026, 9, 26, 10, 0), False),  # Saturday
        (datetime(2026, 12, 25, 10, 0), False),  # Christmas, a Friday
        (datetime(2026, 11, 3, 10, 0), True),  # Melbourne Cup: VIC only, NSW is open
    ],
)
def test_clinic_is_open(local, expected):
    assert clinic_is_open(local.replace(tzinfo=SYDNEY)) is expected


def test_utc_input_is_read_in_clinic_time():
    # 22:30 UTC Sunday is 08:30 Monday in Sydney (AEST, UTC+10).
    assert clinic_is_open(datetime(2026, 9, 27, 22, 30, tzinfo=ZoneInfo("UTC"))) is True
