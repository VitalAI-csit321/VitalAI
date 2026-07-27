"""add priority column to human_review_tasks

Revision ID: 0019_add_task_priority
Revises: 0018_audit_chain_sequence_number
Create Date: 2026-07-27
"""

from alembic import op

revision: str = "0019_add_task_priority"
down_revision: str | None = "0018_audit_chain_sequence_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_priority') THEN
                CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high');
            END IF;
        END $$
    """)
    op.execute(
        "ALTER TABLE human_review_tasks "
        "ADD COLUMN priority task_priority NOT NULL DEFAULT 'medium'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE human_review_tasks DROP COLUMN priority")
    op.execute("DROP TYPE IF EXISTS task_priority")
