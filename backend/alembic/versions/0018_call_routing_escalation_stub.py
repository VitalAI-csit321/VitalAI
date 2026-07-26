"""add calls/tasks tables + call routing/escalation context (Ahnaf's task-call-models)

Revision ID: 0018_call_routing_escalation
Revises:
Create Date: 2026-07-27

Ported from origin/feature/task-call-models (0017_add_call_task_models +
0018_call_routing_escalation squashed into one, idempotent throughout).
That branch's own migration numbering was never reconcilable with this
worktree's chain (its stamp on the shared dev DB predates a later rebase
that renumbered its files -- see the 0016_merge_call_routing migration this
revision feeds into). All DDL here is idempotent: on the real shared dev DB
it already ran out-of-band during an earlier verification session, so every
statement is a no-op there; on a fresh DB it creates the schema for real.
"""

from alembic import op

revision: str = "0018_call_routing_escalation"
down_revision: str | None = "0001_initial"
branch_labels = "call_routing_stub"
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    for name, values in [
        ("call_status", ["received", "processed", "escalated"]),
        ("task_source", ["email", "call"]),
        ("task_priority", ["low", "medium", "high", "urgent"]),
        ("task_status", ["pending", "in_progress", "completed", "escalated"]),
    ]:
        quoted = ", ".join(f"'{v}'" for v in values)
        bind.exec_driver_sql(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN
                    CREATE TYPE {name} AS ENUM ({quoted});
                END IF;
            END $$
        """)
    bind.exec_driver_sql("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'escalated'")

    bind.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS calls (
            case_id             UUID NOT NULL REFERENCES intake_cases(id) ON DELETE CASCADE,
            phone_number        VARCHAR(20) NOT NULL,
            transcript          TEXT,
            status              call_status NOT NULL,
            id                  UUID NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL,
            updated_at          TIMESTAMPTZ NOT NULL,
            triage_id           UUID REFERENCES triage_results(id) ON DELETE SET NULL,
            routing_id          UUID REFERENCES routing_decisions(id) ON DELETE SET NULL,
            urgency_tier        triage_category,
            target_queue        VARCHAR(100),
            routing_overridden  BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (id)
        )
    """)
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_calls_case_id ON calls (case_id)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_calls_triage_id ON calls (triage_id)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_calls_routing_id ON calls (routing_id)"
    )

    bind.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS tasks (
            case_id           UUID NOT NULL REFERENCES intake_cases(id) ON DELETE CASCADE,
            assigned_to       UUID REFERENCES users(id),
            source            task_source NOT NULL,
            priority          task_priority NOT NULL,
            status            task_status NOT NULL,
            id                UUID NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL,
            updated_at        TIMESTAMPTZ NOT NULL,
            call_id           UUID REFERENCES calls(id) ON DELETE CASCADE,
            target_queue      VARCHAR(100),
            handover_context  TEXT,
            PRIMARY KEY (id)
        )
    """)
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_tasks_case_id ON tasks (case_id)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_tasks_assigned_to ON tasks (assigned_to)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_tasks_call_id ON tasks (call_id)"
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("calls")
