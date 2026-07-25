import enum
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.triage import TriageCategory


class CallStatus(enum.StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    ESCALATED = "escalated"


class Call(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "calls"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, name="call_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CallStatus.RECEIVED,
    )
    triage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("triage_results.id", ondelete="SET NULL"), nullable=True, index=True
    )
    routing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("routing_decisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    urgency_tier: Mapped[TriageCategory | None] = mapped_column(
        SAEnum(
            TriageCategory,
            name="triage_category",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    target_queue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    routing_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
