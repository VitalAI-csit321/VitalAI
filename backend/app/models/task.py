import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import UserRole


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


class TaskCategory(enum.StrEnum):
    APPOINTMENT_REQUEST = "appointment_request"
    NEW_PATIENT_ONBOARDING = "new_patient_onboarding"
    PRESCRIPTION_RENEWAL = "prescription_renewal"
    RESULTS_ENQUIRY = "results_enquiry"
    REFERRAL_REQUEST = "referral_request"
    MEDICAL_RECORDS_REQUEST = "medical_records_request"
    BILLING_INSURANCE_ENQUIRY = "billing_insurance_enquiry"
    COMPLAINT_ESCALATION = "complaint_escalation"
    GENERAL_ADMINISTRATIVE = "general_administrative"
    URGENT_EMERGENCY = "urgent_emergency"


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tasks"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=True, index=True
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
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
    target_queue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    handover_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[TaskCategory | None] = mapped_column(
        Enum(TaskCategory, name="task_category", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    target_role: Mapped[UserRole | None] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        index=True,
    )
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_approval_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True
    )
    draft_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
