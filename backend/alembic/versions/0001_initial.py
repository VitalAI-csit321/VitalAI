"""initial schema with append-only audit log
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("front_desk", "ops_manager", "admin", name="user_role"),
            nullable=False,
            server_default="front_desk",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # intake_cases
    op.create_table(
        "intake_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_name", sa.String(255), nullable=False),
        sa.Column("contact_reason", sa.Text(), nullable=False),
        sa.Column("contact_channel", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "intake_received",
                "intake_incomplete",
                "consent_pending",
                "consent_captured",
                "context_ready",
                "context_insufficient",
                "triage_routine",
                "triage_time_sensitive",
                "triage_immediate",
                "routed",
                "escalated",
                name="intake_status",
            ),
            nullable=False,
            server_default="intake_received",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # consent_records
    op.create_table(
        "consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intake_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "captured", "withdrawn", "not_required", name="consent_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_type", sa.String(50), nullable=False, server_default="administrative"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_consent_records_case_id", "consent_records", ["case_id"])

    # triage_results
    op.create_table(
        "triage_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intake_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "routine",
                "time_sensitive",
                "immediate",
                "low_confidence_manual_review",
                name="triage_category",
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_triage_results_case_id", "triage_results", ["case_id"])

    # routing_decisions
    op.create_table(
        "routing_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intake_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("triage_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.Enum(
                "admin_workflow",
                "human_review",
                "direct_escalation",
                name="routing_action",
            ),
            nullable=False,
        ),
        sa.Column("target_queue", sa.String(100), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_routing_decisions_case_id", "routing_decisions", ["case_id"])
    op.create_index("ix_routing_decisions_triage_id", "routing_decisions", ["triage_id"])

    # audit_events — append-only, enforced by trigger below
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intake_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_label", sa.String(255), nullable=False, server_default="system"),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_case_id", "audit_events", ["case_id"])
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])

    # DB-LEVEL APPEND-ONLY ENFORCEMENT.
    # Block UPDATE and DELETE on audit_events via a trigger.
    # The "tamper-evident artefact" claim in the design doc rests on this.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_audit_modification()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only — % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION block_audit_modification();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION block_audit_modification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS block_audit_modification();")

    op.drop_table("audit_events")
    op.drop_table("routing_decisions")
    op.drop_table("triage_results")
    op.drop_table("consent_records")
    op.drop_table("intake_cases")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS routing_action;")
    op.execute("DROP TYPE IF EXISTS triage_category;")
    op.execute("DROP TYPE IF EXISTS consent_status;")
    op.execute("DROP TYPE IF EXISTS intake_status;")
    op.execute("DROP TYPE IF EXISTS user_role;")
