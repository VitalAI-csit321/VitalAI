"""add department to users

Revision ID: 0013_add_user_department
Revises: 0012_clinical_documents
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_add_user_department"
down_revision: str | None = "0012_clinical_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("department", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "department")
