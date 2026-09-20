"""medications table (build spec §12.1)

Reading this table is clinical access, enforced in medication_service rather
than at a route, because the agent graph never passes through one.

Revision ID: 0033_medications
Revises: 0032_appointment_reminder
Create Date: 2026-09-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_medications"
down_revision: str | None = "0032_appointment_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "medications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dosage", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=100), nullable=True),
        # SET NULL so losing a prescriber never deletes the prescription record.
        sa.Column(
            "prescribed_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prescribed_on", sa.Date(), nullable=False),
        sa.Column("last_review_date", sa.Date(), nullable=True),
        sa.Column("repeats_remaining", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "discontinued",
                "expired",
                name="medication_status",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_medications_patient_id", "medications", ["patient_id"])
    op.create_index("ix_medications_status", "medications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_medications_status", table_name="medications")
    op.drop_index("ix_medications_patient_id", table_name="medications")
    op.drop_table("medications")
    sa.Enum(name="medication_status").drop(op.get_bind(), checkfirst=True)
