from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.permission_grant import UserPermissionGrant
from app.models.user import User, UserRole
from app.services.audit_service import record_event


async def set_department(
    db: AsyncSession,
    target: User,
    department: str,
    actor: User,
) -> User:
    target.department = department
    await db.flush()

    await record_event(
        db,
        actor=actor,
        action="user.department_updated",
        details={"user_id": str(target.id), "department": department},
    )
    await db.commit()
    await db.refresh(target)
    return target


async def list_departments(db: AsyncSession) -> list[str]:
    """Every department in use, for the directory's filter. Taken from the
    whole table, not from the page being returned, or a department belonging
    only to users further down the list is never offered."""
    rows = (
        (
            await db.execute(
                select(User.department)
                .where(User.department.is_not(None))
                .distinct()
                .order_by(User.department)
            )
        )
        .scalars()
        .all()
    )
    return [d for d in rows if d]


async def list_users(
    db: AsyncSession,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
    role: UserRole | None = None,
    department: str | None = None,
) -> tuple[list[tuple[User, datetime | None]], int]:
    """A page of users and the total number matching the filters.

    Role and department filter here rather than in the browser: the caller
    receives one page, so filtering after the fact searches only that page and
    reports counts for it, which reads as the whole directory but is not.
    """
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(or_(User.full_name.ilike(term), User.email.ilike(term)))
    if role is not None:
        filters.append(User.role == role)
    if department:
        filters.append(User.department == department)

    last_active_subq = (
        select(func.max(AuditEvent.timestamp))
        .where(AuditEvent.actor_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )

    items_query = select(User, last_active_subq.label("last_active"))
    count_query = select(func.count()).select_from(User)
    for condition in filters:
        items_query = items_query.where(condition)
        count_query = count_query.where(condition)

    items_query = items_query.order_by(User.created_at.desc()).limit(limit).offset(offset)

    total = (await db.execute(count_query)).scalar_one()
    rows = (await db.execute(items_query)).all()
    return [(row.User, row.last_active) for row in rows], total


async def set_active_status(db: AsyncSession, target: User, is_active: bool, actor: User) -> User:
    target.is_active = is_active
    await db.flush()

    await record_event(
        db,
        actor=actor,
        action="user.active_status_changed",
        details={"user_id": str(target.id), "is_active": is_active},
    )
    await db.commit()
    await db.refresh(target)
    return target


async def get_grants(db: AsyncSession, target: User) -> list[str]:
    result = await db.execute(
        select(UserPermissionGrant.permission).where(UserPermissionGrant.user_id == target.id)
    )
    return [row[0] for row in result.all()]
