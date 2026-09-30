import re
import unicodedata
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.config import settings
from app.models.patient import Gender
from app.services.consent_service import CLINIC_CHECKS

_OPTIONAL_TEXT = (
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "preferred_language",
    "preferred_communication",
)


_PHONE = re.compile(r"[0-9 +()\-]+")


class RegistrationDoctor(BaseModel):
    """A doctor the patient may prefer. Name and id only: the form is public."""

    id: UUID
    name: str


class RegistrationLinkOut(BaseModel):
    email: str
    needs_preferred_day: bool
    # The consent wording lives here, so the page shows exactly what is stored.
    # statements: required to register. clauses and clinic_checks: the clinic's
    # own consent, optional here and finished at the clinic.
    statements: list[str]
    clauses: list[str]
    clinic_checks: list[str]
    # Active doctors only (M4, E6): "No preference" is the default.
    doctors: list[RegistrationDoctor]


class RegistrationSubmit(BaseModel):
    """What the public form sends. Unknown fields are refused: the form must
    never become a way to write a column it does not show."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    dob: date
    phone: str = Field(max_length=32)
    gender: Gender | None = None
    address: str | None = Field(default=None, max_length=255)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=255)
    preferred_language: str | None = Field(default=None, max_length=255)
    preferred_communication: str | None = Field(default=None, max_length=255)
    preferred_day: date | None = None
    part_of_day: Literal["morning", "afternoon", "any"] | None = None
    preferred_doctor_id: UUID | None = None
    agree_data: Literal[True]
    agree_contact: Literal[True]
    # One answer per CLINIC_CHECKS statement, in order, or none at all.
    clinic_checks: list[bool] = Field(default_factory=list)
    signature: str | None = Field(
        default=None, max_length=200_000, pattern=r"^data:image/png;base64,[A-Za-z0-9+/=]+$"
    )

    @field_validator(
        "gender", "preferred_day", "part_of_day", "signature", *_OPTIONAL_TEXT, mode="before"
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # An empty input on the form arrives as "".
        return None if isinstance(value, str) and not value.strip() else value

    # PydanticCustomError, not ValueError: its message reaches the patient as
    # written, without pydantic's "Value error, " prefix or a regex.
    @field_validator("dob")
    @classmethod
    def _born_before_today(cls, value: date) -> date:
        # The clinic's today, as _check_day uses, not the server's.
        if value >= datetime.now(ZoneInfo(settings.clinic_timezone)).date():
            raise PydanticCustomError("dob", "Date of birth must be before today.")
        return value

    @field_validator("clinic_checks")
    @classmethod
    def _one_answer_each(cls, value: list[bool]) -> list[bool]:
        if value and len(value) != len(CLINIC_CHECKS):
            raise PydanticCustomError("clinic_checks", "Answer each clinic consent statement once.")
        return value

    @field_validator("phone")
    @classmethod
    def _phone_has_digits(cls, value: str) -> str:
        # At least 6 digits: identity matching compares digits, so "((((((" could
        # never match anyone.
        if not _PHONE.fullmatch(value) or sum(c.isdigit() for c in value) < 6:
            raise PydanticCustomError(
                "phone", "Please enter a phone number with at least 6 digits."
            )
        return value

    @field_validator("name", *_OPTIONAL_TEXT)
    @classmethod
    def _no_control_characters(cls, value: str | None) -> str | None:
        # A NUL byte is refused by Postgres (a 500), and a newline in a name
        # lands inside emails and the Task.
        if value and any(unicodedata.category(c) == "Cc" for c in value):
            raise PydanticCustomError("text", "Please remove special characters.")
        return value
