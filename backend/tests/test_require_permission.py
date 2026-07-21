import pytest
from fastapi import HTTPException

from app.auth.dependencies import require_permission
from app.auth.permissions import MANAGE_USERS
from app.models.user import User, UserRole


async def test_require_permission_allows_when_present():
    admin = User(email="a@example.com", hashed_password="h", full_name="A", role=UserRole.ADMIN)
    admin.permission_grants = []
    dep = require_permission(MANAGE_USERS)
    result = await dep(current_user=admin)
    assert result is admin


async def test_require_permission_denies_when_absent():
    front_desk = User(
        email="f@example.com", hashed_password="h", full_name="F", role=UserRole.FRONT_DESK
    )
    front_desk.permission_grants = []
    dep = require_permission(MANAGE_USERS)
    with pytest.raises(HTTPException) as exc_info:
        await dep(current_user=front_desk)
    assert exc_info.value.status_code == 403
