from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.patient import Gender

_OPTIONAL_TEXT = (
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "preferred_language",
    "preferred_communication",
)


class RegistrationLinkOut(BaseModel):
    email: str
    needs_preferred_day: bool
    # The consent wording lives here, so the page shows exactly what is stored.
    statements: list[str]


class RegistrationSubmit(BaseModel):
    """What the public form sends. Unknown fields are refused: the form must
    never become a way to write a column it does not show."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    dob: date
    phone: str = Field(pattern=r"^[0-9 +()\-]{6,32}$")
    gender: Gender | None = None
    address: str | None = Field(default=None, max_length=255)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=255)
    preferred_language: str | None = Field(default=None, max_length=255)
    preferred_communication: str | None = Field(default=None, max_length=255)
    preferred_day: date | None = None
    part_of_day: Literal["morning", "afternoon", "any"] | None = None
    agree_data: Literal[True]
    agree_contact: Literal[True]
    signature: str = Field(max_length=200_000, pattern=r"^data:image/png;base64,[A-Za-z0-9+/=]+$")

    @field_validator("gender", "preferred_day", "part_of_day", *_OPTIONAL_TEXT, mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # An empty input on the form arrives as "".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("dob")
    @classmethod
    def _born_before_today(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("Date of birth must be before today")
        return value
