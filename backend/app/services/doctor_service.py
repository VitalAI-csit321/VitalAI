from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


async def list_doctors(db: AsyncSession, search: str | None = None) -> list[User]:
    query = select(User).where(User.role == UserRole.DOCTOR, User.is_active.is_(True))
    if search:
        query = query.where(User.full_name.ilike(f"%{search}%"))
    result = await db.execute(query.order_by(User.full_name.asc()))
    return list(result.scalars().all())
