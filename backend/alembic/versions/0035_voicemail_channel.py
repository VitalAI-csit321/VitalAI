"""voicemail channel: call kind, Twilio sids, keypad fields, audio key

Every new column is nullable or defaulted, so existing calls need no backfill
beyond kind's server default ('logged').

ADD VALUE follows 0015/0017: allowed inside the migration transaction on
Postgres 12+ because nothing in this migration uses the new values.

Revision ID: 0035_voicemail_channel
Revises: 0034_email_conversation
Create Date: 2026-09-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0035_voicemail_channel"
down_revision: str | None = "0034_email_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ("in_progress", "recording", "abandoned"):
        op.execute(sa.text(f"ALTER TYPE call_status ADD VALUE IF NOT EXISTS '{value}'"))

    call_kind = postgresql.ENUM("logged", "voicemail", name="call_kind")
    call_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "calls",
        sa.Column(
            "kind",
            postgresql.ENUM(name="call_kind", create_type=False),
            nullable=False,
            server_default="logged",
        ),
    )
    op.add_column("calls", sa.Column("twilio_call_sid", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_calls_twilio_call_sid", "calls", ["twilio_call_sid"])
    op.add_column("calls", sa.Column("twilio_recording_sid", sa.String(64), nullable=True))
    op.add_column("calls", sa.Column("twilio_deleted", sa.Boolean(), nullable=True))
    op.add_column("calls", sa.Column("audio_key", sa.String(255), nullable=True))
    op.add_column("calls", sa.Column("keypad_dob", sa.Date(), nullable=True))
    op.add_column("calls", sa.Column("keypad_intent", sa.String(20), nullable=True))
    op.add_column(
        "calls",
        sa.Column("urgent_pressed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("calls", sa.Column("transcript_quality", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    # The three call_status values stay: Postgres cannot drop an enum value.
    for column in (
        "transcript_quality",
        "urgent_pressed",
        "keypad_intent",
        "keypad_dob",
        "audio_key",
        "twilio_deleted",
        "twilio_recording_sid",
    ):
        op.drop_column("calls", column)
    op.drop_constraint("uq_calls_twilio_call_sid", "calls", type_="unique")
    op.drop_column("calls", "twilio_call_sid")
    op.drop_column("calls", "kind")
    postgresql.ENUM(name="call_kind").drop(op.get_bind(), checkfirst=True)
