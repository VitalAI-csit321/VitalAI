"""add_call_and_task_models

Revision ID: 0014_add_call_task_models
Revises: 0013_add_user_department
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0014_add_call_task_models"
down_revision: Union[str, None] = "0013_add_user_department"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types via PL/pgSQL for idempotence
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'call_status') THEN
                CREATE TYPE call_status AS ENUM ('received', 'processed', 'escalated');
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_source') THEN
                CREATE TYPE task_source AS ENUM ('email', 'call');
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_priority') THEN
                CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'urgent');
            END IF;
        END $$
    """)
    
    op.execute("""
        CREATE TABLE calls (
            id              UUID        NOT NULL DEFAULT gen_random_uuid(),
            case_id         UUID        NOT NULL REFERENCES intake_cases(id) ON DELETE CASCADE,
            phone_number    VARCHAR(20) NOT NULL,
            transcript      TEXT,
            status          call_status NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)
    op.create_index("ix_calls_case_id", "calls", ["case_id"])

    op.execute("""
        CREATE TABLE tasks (
            id          UUID            NOT NULL DEFAULT gen_random_uuid(),
            case_id     UUID            NOT NULL REFERENCES intake_cases(id) ON DELETE CASCADE,
            assigned_to UUID            REFERENCES users(id),
            source      task_source     NOT NULL,
            priority    task_priority   NOT NULL,
            status      task_status     NOT NULL,
            created_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)
    op.create_index("ix_tasks_case_id", "tasks", ["case_id"])
    op.create_index("ix_tasks_assigned_to", "tasks", ["assigned_to"])


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("calls")
    op.execute("DROP TYPE IF EXISTS task_priority")
    op.execute("DROP TYPE IF EXISTS task_source")
    op.execute("DROP TYPE IF EXISTS call_status")
