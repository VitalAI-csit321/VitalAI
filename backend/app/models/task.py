import enum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskSource(enum.StrEnum):
    EMAIL = "email"
    CALL = "call"


class TaskPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskItemStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tasks"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    source: Mapped[TaskSource] = mapped_column(
        Enum(TaskSource, name="task_source", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TaskPriority.MEDIUM,
    )
    status: Mapped[TaskItemStatus] = mapped_column(
        Enum(TaskItemStatus, name="task_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TaskItemStatus.PENDING,
    )
