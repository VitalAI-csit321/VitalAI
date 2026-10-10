"""tasks.email_id: the email a task was opened for

Revision ID: 0040_task_email_id
Revises: 0039_prescription_review_kind
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040_task_email_id"
down_revision: str | None = "0039_prescription_review_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("email_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_email_id_emails", "tasks", "emails", ["email_id"], ["id"], ondelete="SET NULL"
    )
    # ingest_email writes the email, then its task, so a task's email is the
    # last one on its case created no later than the task.
    op.execute(
        sa.text(
            """
            UPDATE tasks t SET email_id = (
                SELECT e.id FROM emails e
                WHERE e.case_id = t.case_id AND e.created_at <= t.created_at
                ORDER BY e.created_at DESC LIMIT 1
            )
            WHERE t.source = 'email'
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_email_id_emails", "tasks", type_="foreignkey")
    op.drop_column("tasks", "email_id")
