import enum
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RoutingAction(enum.StrEnum):
    ADMIN_WORKFLOW = "admin_workflow"
    HUMAN_REVIEW = "human_review"
    DIRECT_ESCALATION = "direct_escalation"


class RoutingDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "routing_decisions"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triage_id: Mapped[UUID] = mapped_column(
        ForeignKey("triage_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[RoutingAction] = mapped_column(
        Enum(RoutingAction, name="routing_action", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    target_queue: Mapped[str] = mapped_column(String(100), nullable=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
