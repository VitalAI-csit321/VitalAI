"""Settings page controls: the login rate limit acts on the running system, and
environment-only values are no longer listed."""

import pytest

from app.config import settings
from app.limiter import limiter
from app.services import settings_service
from app.services.settings_service import SettingsValidationError


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    limiter.reset()


def test_environment_only_values_are_not_listed():
    for key in ("clinic_timezone", "clinic_holiday_region", "synthetic_only"):
        assert key not in settings_service.SETTINGS_REGISTRY
        with pytest.raises(SettingsValidationError, match="Unknown setting"):
            settings_service.validate({key: "x"})


def test_clinic_hours_help_no_longer_points_at_a_removed_row():
    for key in ("clinic_open_hour", "clinic_close_hour"):
        assert "below" not in settings_service.SETTINGS_REGISTRY[key].help


def test_case_close_help_drops_the_keep_open_sentence():
    assert "Keep open" not in settings_service.SETTINGS_REGISTRY["case_close_nudge_days"].help


@pytest.mark.parametrize("value", ["1/minute", "10/minute", "100/hour", "1000/hour"])
def test_login_rate_limit_accepts_attempts_per_minute_or_hour(value):
    assert settings_service.validate({"login_rate_limit": value}) == {"login_rate_limit": value}


@pytest.mark.parametrize("value", ["abc", "0/minute", "5/second", "5 per minute", "1001/hour", ""])
def test_login_rate_limit_rejects_anything_else(value):
    with pytest.raises(SettingsValidationError, match="login_rate_limit"):
        settings_service.validate({"login_rate_limit": value})


async def _failed_logins(client, n: int) -> list[int]:
    codes = []
    for _ in range(n):
        res = await client.post(
            "/api/v1/auth/login", data={"username": "nobody@example.com", "password": "wrong"}
        )
        codes.append(res.status_code)
    return codes


@pytest.mark.asyncio
async def test_a_changed_login_rate_limit_applies_without_a_restart(client, monkeypatch):
    monkeypatch.setattr(settings, "login_rate_limit", "2/minute")
    assert await _failed_logins(client, 3) == [401, 401, 429]

    limiter.reset()
    monkeypatch.setattr(settings, "login_rate_limit", "5/minute")
    assert await _failed_logins(client, 3) == [401, 401, 401]


def test_mailbox_plumbing_is_not_a_clinic_setting():
    for key in (
        "outlook_enabled",
        "outlook_mailbox_address",
        "outlook_poll_interval_seconds",
        "outlook_max_messages_per_poll",
    ):
        assert key not in settings_service.SETTINGS_REGISTRY
