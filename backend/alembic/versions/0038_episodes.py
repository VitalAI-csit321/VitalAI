"""cases as episodes of care: episodes table, episode links, preferred doctor, case review kinds

Revision ID: 0038_episodes
Revises: 0037_review_queue_items
Create Date: 2026-09-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038_episodes"
down_revision: str | None = "0037_review_queue_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = ("case_choice", "case_close")
_LINKED = ("intake_cases", "appointments", "consent_records")
_OPEN = "status IN ('pending', 'in_progress', 'escalated')"


def upgrade() -> None:
    # ADD VALUE follows 0037: allowed in the migration transaction because
    # nothing here writes a row that uses the new values.
    for kind in _KINDS:
        op.execute(f"ALTER TYPE task_type ADD VALUE IF NOT EXISTS '{kind}'")

    op.create_table(
        "episodes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("patient_id", sa.UUID(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("open", "closed", name="episode_status"),
            nullable=False,
        ),
        sa.Column("doctor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nudge_snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_episodes_patient_status", "episodes", ["patient_id", "status"])

    for table in _LINKED:
        op.add_column(
            table,
            sa.Column(
                "episode_id",
                sa.UUID(),
                sa.ForeignKey("episodes.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_episode_id", table, ["episode_id"])

    op.add_column(
        "patients",
        sa.Column("preferred_doctor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
    )

    # A "Close this case?" item is about a case, not a message.
    op.alter_column("human_review_tasks", "case_id", nullable=True)
    op.add_column(
        "human_review_tasks",
        sa.Column(
            "episode_id",
            sa.UUID(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_human_review_open_per_episode",
        "human_review_tasks",
        ["episode_id", "task_type"],
        unique=True,
        postgresql_where=sa.text(f"episode_id IS NOT NULL AND {_OPEN}"),
    )


def downgrade() -> None:
    # Postgres cannot drop an enum value; the two task_type values stay. Their
    # rows go, since the old model cannot load them, and so does any item
    # without a contact, which the restored NOT NULL would refuse.
    kinds = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.execute(
        sa.text(
            f"DELETE FROM human_review_tasks WHERE task_type::text IN ({kinds}) OR case_id IS NULL"
        )
    )
    op.drop_index("uq_human_review_open_per_episode", table_name="human_review_tasks")
    op.drop_column("human_review_tasks", "episode_id")
    op.alter_column("human_review_tasks", "case_id", nullable=False)
    op.drop_column("patients", "preferred_doctor_id")
    for table in _LINKED:
        op.drop_index(f"ix_{table}_episode_id", table_name=table)
        op.drop_column(table, "episode_id")
    op.drop_index("ix_episodes_patient_status", table_name="episodes")
    op.drop_table("episodes")
    op.execute("DROP TYPE episode_status")
