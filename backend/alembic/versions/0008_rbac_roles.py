"""rbac: rename ops_manager to operator, add doctor role

Revision ID: 0008_rbac_roles
Revises: 0007_add_appointments_table
Create Date: 2026-07-22 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_rbac_roles"
down_revision: str | None = "0007_add_appointments_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Native Postgres enum, so ALTER TYPE, not a column retype. Both
    # statements are transaction-safe on PG12+: neither statement's
    # new/renamed value is read by a later statement in this same migration.
    op.execute("ALTER TYPE user_role RENAME VALUE 'ops_manager' TO 'operator'")
    op.execute("ALTER TYPE user_role ADD VALUE 'doctor'")


def downgrade() -> None:
    # Postgres cannot drop an enum value (no ALTER TYPE ... DROP VALUE), so
    # 'doctor' cannot be cleanly removed without recreating the type from
    # scratch. This reverses the rename only and leaves 'doctor' declared,
    # matching the RBAC report's own stance that removing enum values is
    # "the disproportionate operation."
    op.execute("ALTER TYPE user_role RENAME VALUE 'operator' TO 'ops_manager'")