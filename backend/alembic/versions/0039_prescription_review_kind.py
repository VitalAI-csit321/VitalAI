"""review queue kind for repeat prescription requests

Revision ID: 0039_prescription_review_kind
Revises: 0038_episodes
Create Date: 2026-10-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039_prescription_review_kind"
down_revision: str | None = "0038_episodes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE follows 0037/0038: nothing here writes a row that uses it.
    op.execute("ALTER TYPE task_type ADD VALUE IF NOT EXISTS 'prescription_request'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; it stays, its rows go.
    op.execute(
        sa.text("DELETE FROM human_review_tasks WHERE task_type::text = 'prescription_request'")
    )
