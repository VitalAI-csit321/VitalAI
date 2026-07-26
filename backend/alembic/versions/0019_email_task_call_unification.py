"""add emails table, unify task/call category+target_role under TaskCategory

Revision ID: 0019_email_task_call_unification
Revises: 0018_call_routing_escalation
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

from alembic import op

revision: str = "0019_email_task_call_unification"
down_revision: str | None = "0018_call_routing_escalation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_CATEGORY_VALUES = (
    "appointment_request",
    "new_patient_onboarding",
    "prescription_renewal",
    "results_enquiry",
    "referral_request",
    "medical_records_request",
    "billing_insurance_enquiry",
    "complaint_escalation",
    "general_administrative",
    "urgent_emergency",
)


def upgrade() -> None:
    values_sql = ", ".join(f"'{v}'" for v in _TASK_CATEGORY_VALUES)
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_category') THEN
                CREATE TYPE task_category AS ENUM ({values_sql});
            END IF;
        END $$
    """)

    op.create_table(
        "emails",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emails_case_id", "emails", ["case_id"])

    op.add_column(
        "tasks",
        sa.Column("category", ENUM(name="task_category", create_type=False), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("target_role", ENUM(name="user_role", create_type=False), nullable=True),
    )
    op.create_index("ix_tasks_target_role", "tasks", ["target_role"])

    op.add_column(
        "calls",
        sa.Column("category", ENUM(name="task_category", create_type=False), nullable=True),
    )
    op.add_column("calls", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "calls",
        sa.Column("target_role", ENUM(name="user_role", create_type=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calls", "target_role")
    op.drop_column("calls", "confidence")
    op.drop_column("calls", "category")
    op.drop_index("ix_tasks_target_role", table_name="tasks")
    op.drop_column("tasks", "target_role")
    op.drop_column("tasks", "category")
    op.drop_index("ix_emails_case_id", table_name="emails")
    op.drop_table("emails")
    op.execute("DROP TYPE IF EXISTS task_category")
