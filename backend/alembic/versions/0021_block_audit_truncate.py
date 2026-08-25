"""block truncate on audit_events

Revision ID: 0021_block_audit_truncate
Revises: 0020_task_comments
Create Date: 2026-08-14 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021_block_audit_truncate"
down_revision: str | None = "0020_task_comments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0001_initial.py's UPDATE/DELETE triggers are FOR EACH ROW, which Postgres
    # never fires on TRUNCATE. The table-owning role also has implicit TRUNCATE
    # privilege regardless of grants, so without this, that role could wipe the
    # entire hash-chained audit log in one statement. Needs a separate
    # FOR EACH STATEMENT trigger; reuses the same block_audit_modification().
    op.execute(
        """
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION block_audit_modification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;")
