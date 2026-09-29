"""registration form link: token hash and sent/submitted times on email_conversations

All three nullable: no existing conversation has a link.

Revision ID: 0036_patient_form_link
Revises: 0035_voicemail_channel
Create Date: 2026-09-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036_patient_form_link"
down_revision: str | None = "0035_voicemail_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_conversations", sa.Column("form_token_hash", sa.String(64), nullable=True))
    op.add_column(
        "email_conversations",
        sa.Column("form_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_conversations",
        sa.Column("form_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_email_conversations_form_token_hash", "email_conversations", ["form_token_hash"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_email_conversations_form_token_hash", "email_conversations", type_="unique"
    )
    for column in ("form_submitted_at", "form_sent_at", "form_token_hash"):
        op.drop_column("email_conversations", column)
