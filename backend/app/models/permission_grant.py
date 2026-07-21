from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class UserPermissionGrant(Base):
    """A per-user permission grant on top of the role's base permissions.

    Validated against GRANTABLE (app/auth/permissions.py) at the service
    layer, not by a DB constraint — the grantable set is keyed by the
    target user's role, which isn't expressible as a column-level CHECK.
    """

    __tablename__ = "user_permission_grants"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(50), primary_key=True)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
