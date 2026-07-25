from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import GRANTABLE
from app.models.permission_grant import UserPermissionGrant
from app.models.user import User
from app.services.audit_service import record_event


class NotGrantableError(Exception):
    """Raised when `permission` is not in GRANTABLE for the target user's role."""


class DuplicateGrantError(Exception):
    """Raised when `permission` is already granted to the target user."""


class GrantNotFoundError(Exception):
    """Raised when revoking a permission that isn't currently granted."""


async def grant_permission(
    db: AsyncSession, target: User, permission: str, actor: User
) -> UserPermissionGrant:
    allowed = GRANTABLE.get(target.role, set())
    if permission not in allowed:
        raise NotGrantableError(f"'{permission}' is not grantable to role '{target.role.value}'")

    existing = await db.get(UserPermissionGrant, (target.id, permission))
    if existing is not None:
        raise DuplicateGrantError(f"'{permission}' is already granted to this user")

    grant = UserPermissionGrant(user_id=target.id, permission=permission, granted_by=actor.id)
    db.add(grant)
    await db.flush()

    await record_event(
        db,
        actor=actor,
        action="user.permission_granted",
        details={"target_user_id": str(target.id), "permission": permission},
    )
    await db.commit()
    await db.refresh(grant)
    return grant


async def revoke_permission(db: AsyncSession, target: User, permission: str, actor: User) -> None:
    grant = await db.get(UserPermissionGrant, (target.id, permission))
    if grant is None:
        raise GrantNotFoundError(f"'{permission}' is not currently granted to this user")

    await db.delete(grant)
    await record_event(
        db,
        actor=actor,
        action="user.permission_revoked",
        details={"target_user_id": str(target.id), "permission": permission},
    )
    await db.commit()
