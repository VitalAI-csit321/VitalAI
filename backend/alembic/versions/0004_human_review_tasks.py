"""add human_review_tasks table
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_human_review_tasks"
down_revision: Union[str, None] = "0003_vector_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types via PL/pgSQL so the operation is idempotent and the
    # SQLAlchemy DDL visitor (which runs via target_metadata) never races with
    # these statements.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_type') THEN
                CREATE TYPE task_type AS ENUM ('triage_review', 'consent_review', 'escalation_review');
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_status') THEN
                CREATE TYPE task_status AS ENUM ('pending', 'in_progress', 'completed', 'cancelled');
            END IF;
        END $$
    """)
    # Use raw SQL for the table so that SQLAlchemy's DDL visitor does not emit
    # a redundant CREATE TYPE for the enum columns (target_metadata interaction).
    op.execute("""
        CREATE TABLE human_review_tasks (
            id          UUID        NOT NULL DEFAULT gen_random_uuid(),
            case_id     UUID        NOT NULL REFERENCES intake_cases(id) ON DELETE CASCADE,
            triage_id   UUID        REFERENCES triage_results(id) ON DELETE SET NULL,
            task_type   task_type   NOT NULL,
            status      task_status NOT NULL DEFAULT 'pending',
            assigned_to UUID        REFERENCES users(id) ON DELETE SET NULL,
            notes       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS human_review_tasks")
    op.execute("DROP TYPE IF EXISTS task_type")
    op.execute("DROP TYPE IF EXISTS task_status")
