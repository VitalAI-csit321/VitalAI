import enum
from uuid import UUID

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CallStatus(enum.StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    ESCALATED = "escalated"


class Call(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "calls"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, name="call_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CallStatus.RECEIVED,
    )
