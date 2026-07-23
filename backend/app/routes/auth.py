from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_roles
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models.user import User, UserRole
from app.schemas.auth import ElevateRoleRequest, Token, UserOut, UserRegister
from app.schemas.pagination import Page, PageParams

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


@router.get("/users", response_model=Page[UserOut])
async def list_users_endpoint(
    page: PageParams = Depends(),
    role: list[UserRole] | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Paginated user list — backs the User Management (RBAC) page. Admin only,
    consistent with the elevate endpoint below."""
    filters = []
    if role:
        filters.append(User.role.in_(role))
    if is_active is not None:
        filters.append(User.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        filters.append(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))

    count_stmt = select(func.count()).select_from(User)
    page_stmt = select(User)
    if filters:
        count_stmt = count_stmt.where(*filters)
        page_stmt = page_stmt.where(*filters)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(
        page_stmt.order_by(User.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page[UserOut](
        items=[UserOut.model_validate(user) for user in result.scalars().all()],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user_endpoint(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    """Deactivate a user. Admin only.

    Deactivation, not deletion — users are referenced by audit_events.actor_id,
    and that table is append-only by design. Removing the row would orphan the
    trail that the append-only trigger exists to protect.
    """
    if user_id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot deactivate your own account.",
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/{user_id}/reactivate", response_model=UserOut)
async def reactivate_user_endpoint(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = True
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/{user_id}/elevate", response_model=UserOut)
async def elevate_user_role(
    user_id: UUID,
    payload: ElevateRoleRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    """Change a user's role. Admin only."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role = payload.new_role
    await db.commit()
    await db.refresh(user)
    return user


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
