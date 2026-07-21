from app.auth.permissions import (
    CAPTURE_CONSENT,
    MANAGE_USERS,
    READ_AUDIT,
    VIEW_CLINICAL,
    effective_permissions,
)
from app.models.permission_grant import UserPermissionGrant
from app.models.user import User, UserRole


def _user(role: UserRole, granted: list[str] | None = None) -> User:
    user = User(email="x@example.com", hashed_password="h", full_name="X", role=role)
    user.permission_grants = [
        UserPermissionGrant(user_id=user.id, permission=p, granted_by=user.id)
        for p in (granted or [])
    ]
    return user


def test_front_desk_has_no_manage_users():
    assert MANAGE_USERS not in effective_permissions(_user(UserRole.FRONT_DESK))


def test_admin_has_manage_users():
    assert MANAGE_USERS in effective_permissions(_user(UserRole.ADMIN))


def test_doctor_base_permissions_exclude_capture_consent():
    assert CAPTURE_CONSENT not in effective_permissions(_user(UserRole.DOCTOR))


def test_operator_gains_granted_read_audit():
    perms = effective_permissions(_user(UserRole.OPERATOR, granted=[READ_AUDIT]))
    assert READ_AUDIT in perms


def test_operator_without_grant_lacks_read_audit():
    perms = effective_permissions(_user(UserRole.OPERATOR))
    assert READ_AUDIT not in perms


def test_front_desk_grant_attempt_is_ignored():
    """FRONT_DESK has no GRANTABLE entry, so a stray grant row must not leak a permission."""
    perms = effective_permissions(_user(UserRole.FRONT_DESK, granted=[VIEW_CLINICAL]))
    assert VIEW_CLINICAL not in perms
