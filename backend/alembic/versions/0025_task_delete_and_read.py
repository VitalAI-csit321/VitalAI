"""add read_at, deleted_at, deleted_by to tasks (inbox delete + unread fix)

Revision ID: 0025_task_delete_and_read
Revises: 0024_outlook_email_dedup
Create Date: 2026-08-25 00:00:00.000000

Renumbered from 0022_task_delete_and_read as part of the 0021 -> 0024
cross-branch renumber (see 0024_outlook_email_dedup's own docstring).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_task_delete_and_read"
down_revision: str | None = "0024_outlook_email_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_deleted_by_users",
        "tasks",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_deleted_by_users", "tasks", type_="foreignkey")
    op.drop_column("tasks", "deleted_by")
    op.drop_column("tasks", "deleted_at")
    op.drop_column("tasks", "read_at")
