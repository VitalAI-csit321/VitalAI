"""add draft persistence and lifecycle columns to tasks

Revision ID: 0020_task_draft_lifecycle
Revises: 0019_email_task_call_unification
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_task_draft_lifecycle"
down_revision: str | None = "0019_email_task_call_unification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("draft_text", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("draft_approval_id", sa.Uuid(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("draft_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_tasks_draft_approval_id_approval_requests",
        "tasks",
        "approval_requests",
        ["draft_approval_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tasks_draft_approval_id_approval_requests", "tasks", type_="foreignkey"
    )
    op.drop_column("tasks", "draft_sent")
    op.drop_column("tasks", "draft_approval_id")
    op.drop_column("tasks", "draft_text")
