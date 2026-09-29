"""A multi-turn email exchange on one case (email_conversation_service).

Every inbound message is its own graph thread (graph.thread_id), so what one
turn needs from the last, which times we offered and what we asked, cannot
live in the checkpointer. It lives here, one row per case.
"""

import enum
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_jsonb = JSONB().with_variant(JSON(), "sqlite")


class ConversationStage(enum.StrEnum):
    AWAITING_VERIFICATION = "awaiting_verification"
    AWAITING_DETAILS = "awaiting_details"
    AWAITING_CHOICE = "awaiting_choice"
    BOOKED = "booked"
    # A verification reply identified the sender and the original inquiry
    # carried on down its own path.
    VERIFIED = "verified"
    STAFF = "staff"


OPEN_STAGES = frozenset(
    {
        ConversationStage.AWAITING_VERIFICATION,
        ConversationStage.AWAITING_DETAILS,
        ConversationStage.AWAITING_CHOICE,
    }
)


class EmailConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "email_conversations"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # NULL until someone is identified: a first email with no name has no
    # patient to file anything under (Patient.name is NOT NULL).
    patient_id: Mapped[UUID | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
    # The intent of the email that opened the conversation. A reply that
    # answers a verification request is classified on its own words ("Jane
    # Smith, 1/2/1990"), which say nothing about what Jane originally wanted.
    original_intent: Mapped[str] = mapped_column(String(64), nullable=False)
    origin_email_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    # A plain string, not a DB enum: adding a stage is then not a migration.
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    preferred_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    # [{"doctor_id", "doctor_name", "start"}], start an ISO UTC instant. Written
    # only once the offer was actually sent, so "a time we offered" means a
    # time the patient was really shown.
    offered_slots: Mapped[list[dict]] = mapped_column(_jsonb, nullable=False, default=list)
    last_outbound_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Failed turns (unclear, unoffered time, changed DOB). One gets a
    # clarifying reply; the second hands the case to staff.
    clarifications: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The patient's written confirmation of an offered time: the email that
    # made a provisional patient bookable (patient_service.assert_bookable).
    confirmed_email_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    appointment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
