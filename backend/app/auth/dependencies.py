import logging
from typing import NoReturn
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import effective_permissions
from app.auth.security import decode_access_token
from app.database import get_db
from app.models.user import User, UserRole
from app.services.audit_service import record_event

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_error

    raw = payload.get("sub")
    if not isinstance(raw, str):
        raise credentials_error
    user_id_str: str = raw

    try:
        user_id = UUID(user_id_str)
    except ValueError as exc:
        raise credentials_error from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error

    return user


async def _deny(
    db: AsyncSession,
    actor: User,
    *,
    kind: str,
    details: dict,
    detail: str,
) -> NoReturn:
    """Record a governance.access_denied audit event, then always raise 403.

    A failed audit write (e.g. a DB hiccup) is caught and logged rather than
    left to propagate, so a real denial always surfaces as a clean 403, never
    as a 500 that looks like a server error instead of an access decision.
    Flood risk (repeated probing growing the append-only audit_events table)
    is a separate, deliberately deferred concern — see
    docs/superpowers/specs/2026-07-25-governance-follow-ups-design.md section 3.
    """
    try:
        await record_event(
            db,
            actor=actor,
            action="governance.access_denied",
            details={"kind": kind, **details},
        )
        await db.commit()
    except Exception:
        logger.exception("failed to record governance.access_denied audit event")
        await db.rollback()
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_roles(*allowed: UserRole):
    """Dependency factory: returns a dep that 403s if the current user's role
    is not in the allowed set. Denials are logged to the audit trail; grants
    are not (see require_permission() below for the rationale)."""

    async def dep(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if current_user.role not in allowed:
            await _deny(
                db,
                current_user,
                kind="roles",
                details={"allowed": [r.value for r in allowed]},
                detail=f"Role '{current_user.role.value}' not permitted for this action",
            )
        return current_user

    dep.rbac_check = ("roles", frozenset(allowed))  # type: ignore[attr-defined]
    return dep


def require_permission(permission: str):
    """Dependency factory: 403s if `permission` isn't in the caller's effective set.

    This is the primary route gate for the RBAC model. require_roles() above
    is kept only for app/routes/llm.py, which is infra diagnostics outside
    the RBAC report's permission taxonomy.

    A denial writes a `governance.access_denied` AuditEvent and commits it
    directly — app.database.get_db() rolls back the session on the
    HTTPException this raises, so there's no later caller to commit on our
    behalf, and no accompanying business change to commit it alongside
    anyway. A grant writes nothing; only denials are logged, so this doesn't
    flood the audit trail with every successful request.
    """

    async def dep(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if permission not in effective_permissions(current_user):
            await _deny(
                db,
                current_user,
                kind="permission",
                details={"permission": permission},
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    dep.rbac_check = ("permission", frozenset({permission}))  # type: ignore[attr-defined]
    return dep


def require_any_permission(*permissions: str):
    """Dependency factory: 403s unless at least one of `permissions` is held.

    Used where a route accepts two different care-relationship scopes rather
    than one permission (e.g. appointments: MANAGE_APPOINTMENTS_ALL or
    MANAGE_OWN_CALENDAR). Row-level scoping between those cases still runs in
    the handler, same as require_permission(). Denial/audit behavior mirrors
    require_permission() above.
    """

    async def dep(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not set(permissions) & effective_permissions(current_user):
            await _deny(
                db,
                current_user,
                kind="any_permission",
                details={"permissions": list(permissions)},
                detail=f"Missing one of required permissions: {permissions}",
            )
        return current_user

    dep.rbac_check = ("any_permission", frozenset(permissions))  # type: ignore[attr-defined]
    return dep