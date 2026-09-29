"""appointment reminders: reminder_sent_at

The idempotency guard for the 24 hour reminder sweep, playing the role
draft_sent plays for replies. A reminder goes out only while this is NULL,
and the sweep sets it only after a successful send, so the sweep interval
decides how late a reminder can be and never whether it goes twice.

Nullable with no server default on purpose: every existing confirmed
appointment starts un-reminded, which is correct, and NULL is the state the
sweep selects on.

Every path that moves time_slot clears it again, or a patient moved from
Tuesday to Friday after Tuesday's reminder never hears about Friday.

Revision ID: 0032_appointment_reminder
Revises: 0031_provisional_patient
Create Date: 2026-09-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_appointment_reminder"
down_revision: str | None = "0031_provisional_patient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "reminder_sent_at")
