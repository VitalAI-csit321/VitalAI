"""add call and task models

Revision ID: 0014_add_call_task_models
Revises: 0013_add_user_department
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_add_call_task_models"
down_revision: tuple[str, str] = (
    "0013_add_user_department",
    "413c83eda220",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

call_status = postgresql.ENUM(
    "received", "processed", "escalated", name="call_status", create_type=False
)
task_source = postgresql.ENUM("email", "call", name="task_source", create_type=False)
task_priority = postgresql.ENUM(
    "low", "medium", "high", "urgent", name="task_priority", create_type=False
)
task_status = postgresql.ENUM(
    "pending", "in_progress", "completed", "escalated", name="task_status", create_type=False
)


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
