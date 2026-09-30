"""A case: one clinical problem being handled, an episode of care (M4).

Distinct from IntakeCase, which is one message or call (the UI calls it a
"contact"). An episode groups a patient's contacts, appointments and consents
about one problem, opens and closes, and has a doctor. episode_service owns
every write.
"""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class EpisodeStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Episode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (Index("ix_episodes_patient_status", "patient_id", "status"),)

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[EpisodeStatus] = mapped_column(
        Enum(EpisodeStatus, name="episode_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=EpisodeStatus.OPEN,
    )
    # NULL only when no active doctor existed to give it.
    doctor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # The agent account for cases opened automatically.
    opened_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the close nudge (case_nudge) measures staleness by.
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    nudge_snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
