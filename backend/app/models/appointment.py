import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AppointmentStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class AppointmentType(enum.StrEnum):
    NEW_PATIENT = "new_patient"
    FOLLOW_UP = "follow_up"
    PROCEDURE = "procedure"
    OTHER = "other"


class Appointment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "appointments"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("intake_cases.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    time_slot: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointment_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AppointmentStatus.PENDING,
    )

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    appointment_type: Mapped[AppointmentType] = mapped_column(
        Enum(
            AppointmentType,
            name="appointment_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AppointmentType.OTHER,
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Python-side default (not a DB server_default) because each row needs a
    # distinct value. Mirrors migration 0026's own backfill generator. Callers
    # that construct Appointment() without an explicit reference_code -- e.g.
    # the existing book_appointment service, unchanged by this task -- would
    # otherwise hit reference_code's NOT NULL constraint and have it
    # mis-reported as SlotTakenError by that function's catch-all
    # `except IntegrityError`.
    # ponytail: 6 hex chars = ~16.7M values, no uniqueness retry on collision;
    # fine at this volume, add a retry-on-IntegrityError loop if reference
    # codes ever get generated at real scale.
    reference_code: Mapped[str] = mapped_column(
        String(16), nullable=False, default=lambda: f"APT-{secrets.token_hex(3).upper()}"
    )
    notify_patient: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_provider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    series_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # excl_doctor_overlap is a Postgres EXCLUDE constraint and has no SQLAlchemy
    # equivalent; it lives only in migration 0026. Declared here for SQLite runs
    # so duration is still validated when the exclusion constraint is absent.
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_appointment_duration_positive"),
        UniqueConstraint("reference_code", name="unq_appointment_reference_code"),
    )

    @property
    def end_time(self) -> datetime:
        from datetime import timedelta

        return self.time_slot + timedelta(minutes=self.duration_minutes)
