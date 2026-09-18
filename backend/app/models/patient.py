import enum
from datetime import date

from sqlalchemy import Date, Enum, String, Text
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


# The fields that make up a patient's profile completeness (see
# patient_service.is_profile_complete). Adding a field here retroactively
# regresses every currently-ACTIVE patient to PENDING on their next edit,
# since completeness is recomputed from this full list, not versioned.
# ponytail: acceptable today (all-or-nothing completeness was an explicit
# decision) — add migration versioning only if this list actually changes.
PROFILE_FIELDS: tuple[str, ...] = (
    "address",
    "indigenous_status",
    "preferred_language",
    "phone",
    "email",
    "emergency_contact_name",
    "emergency_contact_phone",
    "preferred_communication",
    "best_time_to_contact",
    "known_conditions",
    "current_medications",
    "allergies",
    "insurance_provider",
    "policy_number",
    "group_number",
    "insurance_expiry",
    "medicare_number",
    "concession_card",
)


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
    # `status` conflates two concerns: data-completeness (pending/active,
    # auto-derived — see patient_service.is_profile_complete) and
    # clinical/administrative status (inactive, manually set). No other code
    # path reads PatientStatus.ACTIVE today, so this is safe, but the next
    # feature needing "currently under active care" as its own concept
    # should split it into a separate field rather than extend this one.
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indigenous_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_communication: Mapped[str | None] = mapped_column(String(255), nullable=True)
    best_time_to_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    known_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_medications: Mapped[str | None] = mapped_column(Text, nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    insurance_provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    insurance_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    medicare_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    concession_card: Mapped[str | None] = mapped_column(String(255), nullable=True)
