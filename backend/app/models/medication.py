"""Medications a patient is on (build spec §12.1).

There was no medication model before this: prescriptions existed only as RAG
text chunks, which cannot answer "when was this last reviewed" without a
model reading prose. The prescription branch needs that answer to choose
between two acknowledgements, so the fact becomes a column.

Reading this table is clinical access. medication_service enforces
VIEW_CLINICAL in the service layer, because the agent path never passes
through a route and route dependencies therefore protect nothing there.
"""

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MedicationStatus(enum.StrEnum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    EXPIRED = "expired"


class Medication(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "medications"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # SET NULL, not CASCADE: a doctor leaving the clinic must not delete the
    # record that a medication was prescribed.
    prescribed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    prescribed_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Nullable: a medication carried over from another practice may never have
    # been reviewed here. check_last_review_date treats that as "review due",
    # which is the safe reading.
    last_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    repeats_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[MedicationStatus] = mapped_column(
        Enum(
            MedicationStatus,
            name="medication_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=MedicationStatus.ACTIVE,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
