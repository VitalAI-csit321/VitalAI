"""The voicemail channel (docs/superpowers/specs/2026-09-26-voicemail-channel-design.md).

A caller answers a keypad menu and leaves a message; staff get a callback
task. Nothing here ever sends anything to the caller.
"""

from __future__ import annotations

from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo

import holidays

from app.config import settings


@cache
def _holidays(region: str, year: int) -> holidays.HolidayBase:
    return holidays.country_holidays("AU", subdiv=region, years=year)


def clinic_is_open(now: datetime) -> bool:
    """Weekday, inside clinic hours, not a public holiday, all in clinic time."""
    local = now.astimezone(ZoneInfo(settings.clinic_timezone))
    closed_day = local.date() in _holidays(settings.clinic_holiday_region, local.year)
    if local.weekday() >= 5 or closed_day:
        return False
    return settings.clinic_open_hour <= local.hour < settings.clinic_close_hour
