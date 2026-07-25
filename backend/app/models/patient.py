import enum
from datetime import date

from sqlalchemy import Date, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PatientStatus(enum.StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    INACTIVE = "inactive"


class Gender(enum.StrEnum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"


class Patient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "patients"

    mrn: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="gender", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status: Mapped[PatientStatus] = mapped_column(
        Enum(PatientStatus, name="patient_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PatientStatus.PENDING,
    )
