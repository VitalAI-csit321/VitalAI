"""add appointments table

Revision ID: 0007_add_appointments_table
Revises: 0006_chunk_citation_tag
Create Date: 2026-07-14 18:44:48.911527

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_add_appointments_table"
down_revision: str | None = "0006_chunk_citation_tag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("time_slot", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("suggested", "confirmed", "cancelled", name="appointment_status"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["intake_cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doctor_id", "time_slot", name="unq_doctor_timeslot"),
    )


def downgrade() -> None:
    op.drop_table("appointments")
    op.execute("DROP TYPE IF EXISTS appointment_status")
