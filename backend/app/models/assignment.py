from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class DoctorPatientAssignment(Base):
    """A doctor's care-relationship scope over a patient (RBAC report §6).

    Create/delete only, never edited in place, no updated_at.
    """

    __tablename__ = "doctor_patient_assignments"

    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), primary_key=True)
    assigned_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
