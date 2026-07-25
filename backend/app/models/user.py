import enum

from sqlalchemy import Enum, String
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.permission_grant import UserPermissionGrant


class UserRole(enum.StrEnum):
    FRONT_DESK = "front_desk"
    OPERATOR = "operator"
    ADMIN = "admin"
    DOCTOR = "doctor"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.FRONT_DESK,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    permission_grants: Mapped[list["UserPermissionGrant"]] = relationship(
        UserPermissionGrant,
        foreign_keys=[UserPermissionGrant.user_id],
        lazy="selectin",
    )
    granted_permissions = association_proxy("permission_grants", "permission")
