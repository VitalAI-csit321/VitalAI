from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission, require_permission, require_roles
from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_USERS
from app.models.user import User, UserRole


def _front_desk_user() -> User:
    user = User(
        email="fail-audit@example.com", hashed_password="h", full_name="F", role=UserRole.FRONT_DESK
    )
    user.permission_grants = []
    return user


async def test_require_permission_denial_still_returns_403_when_audit_write_fails(
    db_session: AsyncSession,
):
    dep = require_permission(MANAGE_USERS)

    with patch(
        "app.auth.dependencies.record_event",
        new=AsyncMock(side_effect=RuntimeError("simulated audit-write failure")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=_front_desk_user(), db=db_session)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == f"Missing required permission: {MANAGE_USERS}"


async def test_require_any_permission_denial_still_returns_403_when_audit_write_fails(
    db_session: AsyncSession,
):
    dep = require_any_permission(MANAGE_APPOINTMENTS_ALL)
    doctor = User(email="d@example.com", hashed_password="h", full_name="D", role=UserRole.DOCTOR)
    doctor.permission_grants = []

    with patch(
        "app.auth.dependencies.record_event",
        new=AsyncMock(side_effect=RuntimeError("simulated audit-write failure")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=doctor, db=db_session)

    assert exc_info.value.status_code == 403


async def test_require_roles_denial_still_returns_403_when_audit_write_fails(
    db_session: AsyncSession,
):
    dep = require_roles(UserRole.ADMIN)

    with patch(
        "app.auth.dependencies.record_event",
        new=AsyncMock(side_effect=RuntimeError("simulated audit-write failure")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=_front_desk_user(), db=db_session)

    assert exc_info.value.status_code == 403