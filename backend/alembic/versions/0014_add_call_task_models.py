"""add_call_and_task_models

Revision ID: 0014_add_call_task_models
Revises: 0013_add_user_department
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


def _create_enum_if_not_exists(name: str, values: list[str]) -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"), {"name": name}
    ).scalar()
    if exists:
        return
    quoted = ", ".join(f"'{v}'" for v in values)
    op.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({quoted})"))


revision: str = "0014_add_call_task_models"
down_revision: Union[str, None] = "0013_add_user_department"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _create_enum_if_not_exists("call_status", ["received", "processed", "escalated"])
    _create_enum_if_not_exists("task_source", ["email", "call"])
    _create_enum_if_not_exists("task_priority", ["low", "medium", "high", "urgent"])
    _create_enum_if_not_exists("task_status", ["pending", "in_progress", "completed", "escalated"])

    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("received", "processed", "escalated", name="call_status", create_type=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calls_case_id", "calls", ["case_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("source", sa.Enum("email", "call", name="task_source", create_type=False), nullable=False),
        sa.Column("priority", sa.Enum("low", "medium", "high", "urgent", name="task_priority", create_type=False), nullable=False),
        sa.Column("status", sa.Enum("pending", "in_progress", "completed", "escalated", name="task_status", create_type=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_case_id", "tasks", ["case_id"])
    op.create_index("ix_tasks_assigned_to", "tasks", ["assigned_to"])


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("calls")
