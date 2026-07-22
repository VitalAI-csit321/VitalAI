"""add user_permission_grants table

Revision ID: 0009_permission_grants
Revises: 0008_rbac_roles
Create Date: 2026-07-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_permission_grants"
down_revision: str | None = "0008_rbac_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_permission_grants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(length=50), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "permission"),
    )


def downgrade() -> None:
    op.drop_table("user_permission_grants")
