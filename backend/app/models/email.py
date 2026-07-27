from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Email(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "emails"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
