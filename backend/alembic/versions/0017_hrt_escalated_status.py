"""add escalated value to human review task_status enum

Revision ID: 0017_hrt_escalated_status
Revises: 0016_audit_hash_chain
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0017_hrt_escalated_status"
down_revision: str | None = "0016_merge_call_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'escalated'"))


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; downgrading this value is a no-op.
    pass
