import pytest
from fastapi import HTTPException

from app.auth.dependencies import require_any_permission
from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR
from app.models.user import User, UserRole


async def test_require_any_permission_allows_first_permission():
    front_desk = User(
        email="f@example.com", hashed_password="h", full_name="F", role=UserRole.FRONT_DESK
    )
    front_desk.permission_grants = []
    dep = require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)
    result = await dep(current_user=front_desk)
    assert result is front_desk


async def test_require_any_permission_allows_second_permission():
    doctor = User(email="d@example.com", hashed_password="h", full_name="D", role=UserRole.DOCTOR)
    doctor.permission_grants = []
    dep = require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)
    result = await dep(current_user=doctor)
    assert result is doctor


async def test_require_any_permission_denies_when_neither_present():
    doctor = User(email="d2@example.com", hashed_password="h", full_name="D2", role=UserRole.DOCTOR)
    doctor.permission_grants = []
    dep = require_any_permission(MANAGE_APPOINTMENTS_ALL)
    with pytest.raises(HTTPException) as exc_info:
        await dep(current_user=doctor)
    assert exc_info.value.status_code == 403
