"""add target_role to human_review_tasks, add routing_review task_type value

Revision ID: 0015_human_review_target_role
Revises: 0014_approval_requests
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

from alembic import op

revision: str = "0015_human_review_target_role"
down_revision: str | None = "0014_approval_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS (PG12+) makes this safe to re-run after a downgrade,
    # since downgrade() cannot remove the enum value once added (see below).
    op.execute("ALTER TYPE task_type ADD VALUE IF NOT EXISTS 'routing_review'")
    op.add_column(
        "human_review_tasks",
        sa.Column(
            "target_role", PGEnum(name="user_role", create_type=False), nullable=True
        ),
    )
    op.create_index(
        "ix_human_review_tasks_target_role", "human_review_tasks", ["target_role"]
    )


def downgrade() -> None:
    op.drop_index("ix_human_review_tasks_target_role", table_name="human_review_tasks")
    op.drop_column("human_review_tasks", "target_role")
    # Postgres cannot drop an enum value; 'routing_review' stays declared,
    # matching the RBAC report's additive-only convention (see 0008_rbac_roles).
