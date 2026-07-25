"""ApprovalRequest: HITL governance gate (FR-GOV-01).

See docs/superpowers/specs/2026-07-24-fr-gov-01-approval-gate-design.md.
Separate from HumanReviewTask (app/models/human_review.py), which is a
claim/work-queue concept; this is a binary approve/reject decision.
"""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, utcnow

_jsonb = JSONB().with_variant(JSON(), "sqlite")


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRequest(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "approval_requests"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(_jsonb, nullable=False, default=dict)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_label: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(
            ApprovalStatus,
            name="approval_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ApprovalStatus.PENDING,
        index=True,
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_payload: Mapped[dict | None] = mapped_column(_jsonb, nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
