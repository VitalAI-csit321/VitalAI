"""email conversations: reply threading columns + email_conversations

Behind email_booking_conversation_enabled. The emails columns let a reply find
its case by its In-Reply-To/References headers and let the booking flow read
only what the patient wrote in this message. email_conversations carries what
one turn of a multi-turn exchange needs from the previous one, since every
inbound message is its own graph thread.

All new emails columns are nullable (or defaulted), so existing rows need no
backfill.

Revision ID: 0034_email_conversation
Revises: 0033_medications
Create Date: 2026-09-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0034_email_conversation"
down_revision: str | None = "0033_medications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("emails", sa.Column("sender_name", sa.String(length=255), nullable=True))
    op.add_column("emails", sa.Column("internet_message_id", sa.String(length=998), nullable=True))
    op.create_index("ix_emails_internet_message_id", "emails", ["internet_message_id"])
    op.add_column("emails", sa.Column("in_reply_to", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("references_header", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("new_text", sa.Text(), nullable=True))
    op.add_column(
        "emails",
        sa.Column("auto_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "email_conversations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "case_id",
            sa.UUID(),
            sa.ForeignKey("intake_cases.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("patient_id", sa.UUID(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("original_intent", sa.String(length=64), nullable=False),
        sa.Column(
            "origin_email_id",
            sa.UUID(),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("preferred_day", sa.Date(), nullable=True),
        sa.Column(
            "offered_slots",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_outbound_text", sa.Text(), nullable=True),
        sa.Column("clarifications", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_email_id",
            sa.UUID(),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "appointment_id",
            sa.UUID(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("email_conversations")
    op.drop_column("emails", "auto_submitted")
    op.drop_column("emails", "new_text")
    op.drop_column("emails", "references_header")
    op.drop_column("emails", "in_reply_to")
    op.drop_index("ix_emails_internet_message_id", table_name="emails")
    op.drop_column("emails", "internet_message_id")
    op.drop_column("emails", "sender_name")
