import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class AppointmentStatus (enum.StrEnum):
    SUGGESTED = 'suggested'
    CONFIRMED = 'confirmed'
    CANCELLED = 'cancelled'

class Appointment (Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = 'appointments'

    # Foreign key linking to the patient's intake case
    case_id: Mapped[uuid.UUID] = mapped_column (
        ForeignKey ('intake_cases.id'),
        nullable=False,
    )
    
    # Foreign key linking to the doctor (user with a doctor role)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id'),
        nullable=False,
    )

    # The scheduled date and time for the appointment
    time_slot: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Appointment lifecycle status, stored as a Postgres enum type
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name = 'appointment_status',
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable = False,
        default = AppointmentStatus.SUGGESTED,
    )
    # A unique constraint to prevent double booking
    __table_args__ = (
        UniqueConstraint ('doctor_id', 'time_slot', name = 'unq_doctor_timeslot'),
    )

