import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# JSONB on Postgres, plain JSON on SQLite. Same pattern as app/models/audit.py.
_jsonb = JSONB().with_variant(JSON(), "sqlite")


class ConsentStatus(enum.StrEnum):
    PENDING = "pending"
    CAPTURED = "captured"
    WITHDRAWN = "withdrawn"
    NOT_REQUIRED = "not_required"


class ConsentRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "consent_records"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ConsentStatus] = mapped_column(
        Enum(ConsentStatus, name="consent_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ConsentStatus.PENDING,
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="administrative")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_snapshot: Mapped[dict | None] = mapped_column(_jsonb, nullable=True)
