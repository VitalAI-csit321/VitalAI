"""add approval_requests table (FR-GOV-01 HITL approval gate)

Revision ID: 0014_approval_requests
Revises: 0013_add_user_department
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0014_approval_requests"
down_revision: str | None = "0013_add_user_department"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "requested_by_label",
            sa.String(length=255),
            nullable=False,
            server_default="system",
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="approval_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_payload", JSONB(), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approval_requests_action_type", "approval_requests", ["action_type"])
    op.create_index("ix_approval_requests_case_id", "approval_requests", ["case_id"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])


def downgrade() -> None:
    op.drop_table("approval_requests")
    op.execute("DROP TYPE IF EXISTS approval_status")
