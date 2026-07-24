import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission, require_permission, require_roles
from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR, MANAGE_USERS
from app.models.audit import AuditEvent
from app.models.user import User, UserRole


def _user(role: UserRole) -> User:
    user = User(email=f"{role.value}@rbac-dep-test.example.com", hashed_password="h", full_name="X", role=role)
    user.permission_grants = []
    return user


async def _persist(db_session: AsyncSession, user: User) -> User:
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# --- metadata tagging ---


def test_require_permission_tags_rbac_check():
    dep = require_permission(MANAGE_USERS)
    assert dep.rbac_check == ("permission", frozenset({MANAGE_USERS}))


def test_require_any_permission_tags_rbac_check():
    dep = require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)
    assert dep.rbac_check == (
        "any_permission",
        frozenset({MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR}),
    )


def test_require_roles_tags_rbac_check():
    dep = require_roles(UserRole.ADMIN, UserRole.OPERATOR)
    assert dep.rbac_check == ("roles", frozenset({UserRole.ADMIN, UserRole.OPERATOR}))


# --- audit-on-deny ---


async def test_require_permission_denial_writes_audit_event(db_session: AsyncSession):
    front_desk = await _persist(db_session, _user(UserRole.FRONT_DESK))

    dep = require_permission(MANAGE_USERS)
    with pytest.raises(HTTPException) as exc_info:
        await dep(current_user=front_desk, db=db_session)
    assert exc_info.value.status_code == 403

    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == front_desk.id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].action == "governance.access_denied"
    assert events[0].details == {"kind": "permission", "permission": MANAGE_USERS}


async def test_require_permission_grant_writes_no_audit_event(db_session: AsyncSession):
    admin = await _persist(db_session, _user(UserRole.ADMIN))

    dep = require_permission(MANAGE_USERS)
    result = await dep(current_user=admin, db=db_session)
    assert result is admin

    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == admin.id)))
        .scalars()
        .all()
    )
    assert len(events) == 0


async def test_require_any_permission_denial_writes_audit_event(db_session: AsyncSession):
    doctor = await _persist(db_session, _user(UserRole.DOCTOR))

    dep = require_any_permission(MANAGE_APPOINTMENTS_ALL)
    with pytest.raises(HTTPException):
        await dep(current_user=doctor, db=db_session)

    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == doctor.id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].action == "governance.access_denied"
    assert events[0].details == {"kind": "any_permission", "permissions": [MANAGE_APPOINTMENTS_ALL]}


async def test_require_roles_denial_writes_audit_event(db_session: AsyncSession):
    front_desk = await _persist(db_session, _user(UserRole.FRONT_DESK))

    dep = require_roles(UserRole.ADMIN)
    with pytest.raises(HTTPException):
        await dep(current_user=front_desk, db=db_session)

    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == front_desk.id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].action == "governance.access_denied"
    assert events[0].details == {"kind": "roles", "allowed": [UserRole.ADMIN.value]}
