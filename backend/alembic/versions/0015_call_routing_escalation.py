"""add call routing and escalation context

Revision ID: 0015_call_routing_escalation
Revises: 0014_add_call_task_models
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_call_routing_escalation"
down_revision: str | None = "0014_add_call_task_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
    """
    ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'escalated'
    """
)
    op.add_column("calls", sa.Column("triage_id", sa.Uuid(), nullable=True))
    op.add_column("calls", sa.Column("routing_id", sa.Uuid(), nullable=True))
    op.add_column(
        "calls",
        sa.Column(
            "urgency_tier",
            sa.Enum(
                "routine",
                "time_sensitive",
                "immediate",
                "low_confidence_manual_review",
                name="triage_category",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column("calls", sa.Column("target_queue", sa.String(length=100), nullable=True))
    op.add_column(
        "calls",
        sa.Column("routing_overridden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(op.f("ix_calls_triage_id"), "calls", ["triage_id"], unique=False)
    op.create_index(op.f("ix_calls_routing_id"), "calls", ["routing_id"], unique=False)
    op.create_foreign_key(
        "fk_calls_triage_id_triage_results",
        "calls",
        "triage_results",
        ["triage_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_calls_routing_id_routing_decisions",
        "calls",
        "routing_decisions",
        ["routing_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("tasks", sa.Column("call_id", sa.Uuid(), nullable=True))
    op.add_column("tasks", sa.Column("target_queue", sa.String(length=100), nullable=True))
    op.add_column("tasks", sa.Column("handover_context", sa.Text(), nullable=True))
    op.create_index(op.f("ix_tasks_call_id"), "tasks", ["call_id"], unique=False)
    op.create_foreign_key(
        "fk_tasks_call_id_calls",
        "tasks",
        "calls",
        ["call_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_call_id_calls", "tasks", type_="foreignkey")
    op.drop_index(op.f("ix_tasks_call_id"), table_name="tasks")
    op.drop_column("tasks", "handover_context")
    op.drop_column("tasks", "target_queue")
    op.drop_column("tasks", "call_id")

    op.drop_constraint("fk_calls_routing_id_routing_decisions", "calls", type_="foreignkey")
    op.drop_constraint("fk_calls_triage_id_triage_results", "calls", type_="foreignkey")
    op.drop_index(op.f("ix_calls_routing_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_triage_id"), table_name="calls")
    op.drop_column("calls", "routing_overridden")
    op.drop_column("calls", "target_queue")
    op.drop_column("calls", "urgency_tier")
    op.drop_column("calls", "routing_id")
    op.drop_column("calls", "triage_id")
