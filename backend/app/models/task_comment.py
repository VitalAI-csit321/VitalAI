from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskComment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "task_comments"

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
