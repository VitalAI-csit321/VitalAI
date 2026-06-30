from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.database import get_db
from app.models.user import User, UserRole

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


def require_roles(*allowed: UserRole):
    """Dependency factory: returns a dep that 403s if the current user's role
    is not in the allowed set."""

    async def dep(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role.value}' not permitted for this action",
            )
        return current_user

    return dep
