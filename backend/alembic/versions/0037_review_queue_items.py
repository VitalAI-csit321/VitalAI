"""review queue items: new kinds, approval/inbox links, details, one open item per message

Revision ID: 0037_review_queue_items
Revises: 0036_patient_form_link
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037_review_queue_items"
down_revision: str | None = "0036_patient_form_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "draft_approval",
    "intent_review",
    "identity_review",
    "agent_failure",
    "agent_handover",
    "complaint_review",
)


def upgrade() -> None:
    # ADD VALUE follows 0015/0035: allowed inside the migration transaction as
    # long as no row uses the new value in it, and nothing here writes rows.
    for kind in _KINDS:
        op.execute(f"ALTER TYPE task_type ADD VALUE IF NOT EXISTS '{kind}'")
    op.add_column(
        "human_review_tasks",
        sa.Column(
            "approval_id",
            sa.UUID(),
            sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_human_review_tasks_approval_id", "human_review_tasks", ["approval_id"])
    op.add_column(
        "human_review_tasks",
        sa.Column(
            "inbox_task_id",
            sa.UUID(),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("human_review_tasks", sa.Column("details", postgresql.JSONB(), nullable=True))
    op.create_index(
        "uq_human_review_open_per_message",
        "human_review_tasks",
        ["inbox_task_id", "task_type"],
        unique=True,
        postgresql_where=sa.text(
            "inbox_task_id IS NOT NULL AND status IN ('pending', 'in_progress', 'escalated')"
        ),
    )


def downgrade() -> None:
    # Postgres cannot drop an enum value; the six task_type values stay. Their
    # rows go, since the old model cannot load them.
    kinds = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.execute(sa.text(f"DELETE FROM human_review_tasks WHERE task_type::text IN ({kinds})"))
    op.drop_index("uq_human_review_open_per_message", table_name="human_review_tasks")
    op.drop_column("human_review_tasks", "details")
    op.drop_column("human_review_tasks", "inbox_task_id")
    op.drop_index("ix_human_review_tasks_approval_id", table_name="human_review_tasks")
    op.drop_column("human_review_tasks", "approval_id")
