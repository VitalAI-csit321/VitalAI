"""add call and task models

Revision ID: 0014_add_call_task_models
Revises: 0013_add_user_department
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_add_call_task_models"
down_revision: tuple[str, str] = (
    "0013_add_user_department",
    "413c83eda220",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

call_status = postgresql.ENUM(
    "received", "processed", "escalated", name="call_status", create_type=False
)
task_source = postgresql.ENUM("email", "call", name="task_source", create_type=False)
task_priority = postgresql.ENUM(
    "low", "medium", "high", "urgent", name="task_priority", create_type=False
)
task_status = postgresql.ENUM(
    "pending", "in_progress", "completed", "escalated", name="task_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("received", "processed", "escalated", name="call_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("email", "call", name="task_source").create(bind, checkfirst=True)
    postgresql.ENUM("low", "medium", "high", "urgent", name="task_priority").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "pending", "in_progress", "completed", "escalated", name="task_status"
    ).create(bind, checkfirst=True)

    op.create_table(
        "calls",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("status", call_status, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_calls_case_id"), "calls", ["case_id"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("source", task_source, nullable=False),
        sa.Column("priority", task_priority, nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_assigned_to"), "tasks", ["assigned_to"], unique=False)
    op.create_index(op.f("ix_tasks_case_id"), "tasks", ["case_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_case_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_assigned_to"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_calls_case_id"), table_name="calls")
    op.drop_table("calls")

    bind = op.get_bind()
    task_status.drop(bind, checkfirst=True)
    task_priority.drop(bind, checkfirst=True)
    task_source.drop(bind, checkfirst=True)
    call_status.drop(bind, checkfirst=True)
