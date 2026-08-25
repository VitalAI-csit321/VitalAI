"""add external message provenance to emails for Outlook dedupe

Revision ID: 0021_outlook_email_dedup
Revises: 0020_task_comments
Create Date: 2026-08-20 00:00:00.000000

Renumber before merging to main if 0021_block_audit_truncate (on
feature/rag-org-corpus-hardening) lands first: this must become
0024_outlook_email_dedup with down_revision 0023_chunks_hybrid_search,
otherwise alembic resolves two heads and `upgrade head` fails.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021_outlook_email_dedup"
down_revision: str | None = "0020_task_comments"
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
