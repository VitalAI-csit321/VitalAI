import enum
from uuid import UUID

from sqlalchemy import JSON, Enum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import UserRole


class TaskType(enum.StrEnum):
    TRIAGE_REVIEW = "triage_review"
    CONSENT_REVIEW = "consent_review"
    ESCALATION_REVIEW = "escalation_review"
    ROUTING_REVIEW = "routing_review"
    # Opened by the system (app/services/review_routing.py), one per message and kind.
    DRAFT_APPROVAL = "draft_approval"
    INTENT_REVIEW = "intent_review"
    IDENTITY_REVIEW = "identity_review"
    AGENT_FAILURE = "agent_failure"
    AGENT_HANDOVER = "agent_handover"
    COMPLAINT_REVIEW = "complaint_review"
    # Cases (M4, episode_service): which open case a message belongs to, and
    # whether a quiet case can close. CASE_CLOSE is about a case, not a
    # message, so it has episode_id and no case_id.
    CASE_CHOICE = "case_choice"
    CASE_CLOSE = "case_close"


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


class TaskPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_jsonb = JSONB().with_variant(JSON(), "sqlite")
# One open item per message and kind. review_routing.open_item checks first;
# this is the backstop for a LangGraph node re-run on resume. Consent and
# manual items have no message and are not limited.
_OPEN_PER_MESSAGE = (
    "inbox_task_id IS NOT NULL AND status IN ('pending', 'in_progress', 'escalated')"
)
# The same backstop for items about a case (the hourly close nudge).
_OPEN_PER_EPISODE = "episode_id IS NOT NULL AND status IN ('pending', 'in_progress', 'escalated')"


class HumanReviewTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "human_review_tasks"

    __table_args__ = (
        Index(
            "uq_human_review_open_per_message",
            "inbox_task_id",
            "task_type",
            unique=True,
            postgresql_where=text(_OPEN_PER_MESSAGE),
            sqlite_where=text(_OPEN_PER_MESSAGE),
        ),
        Index(
            "uq_human_review_open_per_episode",
            "episode_id",
            "task_type",
            unique=True,
            postgresql_where=text(_OPEN_PER_EPISODE),
            sqlite_where=text(_OPEN_PER_EPISODE),
        ),
    )

    # The contact the item is about. NULL only for an item about a case
    # (CASE_CLOSE), which carries episode_id instead.
    case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=True
    )
    episode_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True
    )
    triage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("triage_results.id", ondelete="SET NULL"), nullable=True
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(
            TaskType,
            name="task_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=TaskStatus.PENDING,
    )
    target_role: Mapped[UserRole | None] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
        index=True,
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(
            TaskPriority,
            name="task_priority",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=TaskPriority.MEDIUM,
    )
    # The held draft's approval (DRAFT_APPROVAL only): approving or rejecting
    # it, from either screen, closes this item (approval_service).
    approval_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The inbox message the item is about, so the two screens find each other.
    inbox_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    # Kind-specific: identity candidates, the classifier's category, the failed
    # stage, who escalated it and why.
    details: Mapped[dict | None] = mapped_column(_jsonb, nullable=True)
