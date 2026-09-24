from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, false
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

    # Provenance for mail pulled from an external mailbox. NULL for emails
    # created through POST /email/ingest directly (simulated/seeded), which is
    # why these are nullable rather than defaulted. The unique index over the
    # pair (see alembic 0024_outlook_email_dedup) is what actually stops the
    # poller re-ingesting the same message: marking it read in the mailbox is a
    # courtesy, not a correctness guarantee, since that call can fail.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Threading and reply parsing (email_conversation_service). All nullable:
    # a directly ingested email has none of them, and nothing reads them with
    # email_booking_conversation_enabled off.
    # The From header's display name, one of the places a first email's
    # sender name can come from.
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # RFC 5322 Message-ID. A patient's reply carries it in References, which
    # is how the reply finds its case.
    internet_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True, index=True)
    in_reply_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The part of the body the sender wrote in this message, without the
    # quoted history underneath (Graph's uniqueBody). NULL means "not known",
    # and readers fall back to reply_parsing.strip_quoted(body).
    new_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # An out-of-office or other machine reply. Never answered automatically:
    # two auto-responders answering each other is a mail loop.
    auto_submitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
