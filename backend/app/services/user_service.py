from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.permission_grant import UserPermissionGrant
from app.models.user import User
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


async def list_users(
    db: AsyncSession,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[User, datetime | None]], int]:
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(or_(User.full_name.ilike(term), User.email.ilike(term)))

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
