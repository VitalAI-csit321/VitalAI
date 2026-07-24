from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.permissions import MANAGE_USERS
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models.permission_grant import UserPermissionGrant
from app.models.user import User, UserRole
from app.schemas.auth import (
    DepartmentUpdateRequest,
    ElevateRoleRequest,
    Token,
    UserListItem,
    UserListResponse,
    UserOut,
    UserRegister,
)
from app.schemas.permission import PermissionGrantCreate, PermissionGrantOut
from app.services import audit_service, permission_service, user_service
from app.services.permission_service import (
    DuplicateGrantError,
    GrantNotFoundError,
    NotGrantableError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.FRONT_DESK,  # role in payload is always ignored
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/{user_id}/elevate", response_model=UserOut)
async def elevate_user_role(
    user_id: UUID,
    payload: ElevateRoleRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_USERS)),
) -> User:
    """Change a user's role. Admin only."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    old_role = user.role
    user.role = payload.new_role
    await db.flush()

    await audit_service.record_event(
        db,
        actor=actor,
        action="user.role_changed",
        details={
            "user_id": str(user_id),
            "old_role": old_role.value,
            "new_role": payload.new_role.value,
        },
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/{user_id}/department", response_model=UserOut)
async def set_department_endpoint(
    user_id: UUID,
    payload: DepartmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_USERS)),
) -> User:
    """Set a user's department. Admin only."""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await user_service.set_department(db, target, payload.department, actor)


@router.get("/users", response_model=UserListResponse)
async def list_users_endpoint(
    search: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(MANAGE_USERS)),
) -> UserListResponse:
    rows, total = await user_service.list_users(db, search=search, limit=limit, offset=offset)
    return UserListResponse(
        items=[
            UserListItem(**UserOut.model_validate(user).model_dump(), last_active=last_active)
            for user, last_active in rows
        ],
        total=total,
    )


@router.post(
    "/users/{user_id}/grants",
    response_model=PermissionGrantOut,
    status_code=status.HTTP_201_CREATED,
)
async def grant_permission_endpoint(
    user_id: UUID,
    payload: PermissionGrantCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_USERS)),
) -> UserPermissionGrant:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        return await permission_service.grant_permission(db, target, payload.permission, actor)
    except NotGrantableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except DuplicateGrantError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/users/{user_id}/grants/{permission}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission_endpoint(
    user_id: UUID,
    permission: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_USERS)),
) -> None:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        await permission_service.revoke_permission(db, target, permission, actor)
    except GrantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/login", response_model=Token)
@limiter.limit(settings.login_rate_limit)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    token = create_access_token(user.id, user.role)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
