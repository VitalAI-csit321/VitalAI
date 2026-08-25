"""add external message provenance to emails for Outlook dedupe

Revision ID: 0024_outlook_email_dedup
Revises: 0023_chunks_hybrid_search
Create Date: 2026-08-20 00:00:00.000000

Renumbered from 0021_outlook_email_dedup: feature/rag-org-corpus-hardening's
0021_block_audit_truncate -> 0022_chunks_org_wide -> 0023_chunks_hybrid_search
landed first off the same 0020_task_comments base, so this chain moves to
0024/0025 to keep a single alembic head.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024_outlook_email_dedup"
down_revision: str | None = "0023_chunks_hybrid_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("emails", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.add_column("emails", sa.Column("external_source", sa.String(length=50), nullable=True))
    # Partial unique index, not a plain unique constraint: emails ingested
    # directly through POST /email/ingest have no external id, and NULLs must
    # stay unconstrained so any number of them can coexist. This index is the
    # real guarantee that a polled message is ingested at most once.
    op.create_index(
        "ix_emails_external_id_source",
        "emails",
        ["external_id", "external_source"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_emails_external_id_source", table_name="emails")
    op.drop_column("emails", "external_source")
    op.drop_column("emails", "external_id")
