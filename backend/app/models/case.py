import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IntakeStatus(enum.StrEnum):
    RECEIVED = "intake_received"
    INCOMPLETE = "intake_incomplete"
    CONSENT_PENDING = "consent_pending"
    CONSENT_CAPTURED = "consent_captured"
    CONTEXT_READY = "context_ready"
    CONTEXT_INSUFFICIENT = "context_insufficient"
    TRIAGE_ROUTINE = "triage_routine"
    TRIAGE_TIME_SENSITIVE = "triage_time_sensitive"
    TRIAGE_IMMEDIATE = "triage_immediate"
    ROUTED = "routed"
    ESCALATED = "escalated"


class IntakeCase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "intake_cases"

    patient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_reason: Mapped[str] = mapped_column(Text, nullable=False)
    contact_channel: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[IntakeStatus] = mapped_column(
        Enum(IntakeStatus, name="intake_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=IntakeStatus.RECEIVED,
    )
