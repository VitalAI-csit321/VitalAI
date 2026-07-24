"""add patients table and link intake_cases to patients

Revision ID: 0010_patients
Revises: 0009_permission_grants
Create Date: 2026-07-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_patients"
down_revision: str | None = "0009_permission_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mrn", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dob", sa.Date(), nullable=False),
        sa.Column("gender", sa.Enum("male", "female", "non_binary", name="gender"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "pending", "inactive", name="patient_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mrn"),
    )

    op.add_column("intake_cases", sa.Column("patient_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_intake_cases_patient_id_patients",
        "intake_cases",
        "patients",
        ["patient_id"],
        ["id"],
    )
    op.alter_column(
        "intake_cases",
        "patient_name",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    # Only safe to run against data with no null patient_name (i.e. before any
    # post-Phase-2 intake was created) -- same one-way-limitation stance Phase
    # 1's migration took for the ops_manager->operator enum rename.
    op.alter_column(
        "intake_cases",
        "patient_name",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_constraint("fk_intake_cases_patient_id_patients", "intake_cases", type_="foreignkey")
    op.drop_column("intake_cases", "patient_id")
    op.drop_table("patients")
    op.execute("DROP TYPE IF EXISTS gender")
    op.execute("DROP TYPE IF EXISTS patient_status")
