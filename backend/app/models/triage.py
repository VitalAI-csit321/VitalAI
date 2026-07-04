import enum
from uuid import UUID

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TriageCategory(enum.StrEnum):
    ROUTINE = "routine"
    TIME_SENSITIVE = "time_sensitive"
    IMMEDIATE = "immediate"
    LOW_CONFIDENCE = "low_confidence_manual_review"


class TriageResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "triage_results"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[TriageCategory] = mapped_column(
        Enum(
            TriageCategory, name="triage_category", values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    routed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
