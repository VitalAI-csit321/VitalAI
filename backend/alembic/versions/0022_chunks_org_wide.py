"""allow org-wide chunks (nullable patient_id)

chunks.patient_id was NOT NULL with no escape hatch for non-patient content
(clinic policy, routing rules, guardrails, ...). NULL patient_id now means
"applies to every patient context" -- _security_filter in app/rag/retrieval.py
matches patient_id == ctx.patient_id OR patient_id IS NULL, still gated by
access_scope. See docs/FR-RAG-01_handoff.md and the org-profile corpus at
"Organization Profile Review/" for the doc_type -> access_scope mapping this
unblocks.

Revision ID: 0022_chunks_org_wide
Revises: 0021_block_audit_truncate
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022_chunks_org_wide"
down_revision: Union[str, None] = "0021_block_audit_truncate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ALTER COLUMN patient_id DROP NOT NULL")


def downgrade() -> None:
    # Org-wide (NULL patient_id) chunks have no patient to backfill -- delete
    # them before re-adding NOT NULL, or the ALTER fails on existing NULLs.
    op.execute("DELETE FROM chunks WHERE patient_id IS NULL")
    op.execute("ALTER TABLE chunks ALTER COLUMN patient_id SET NOT NULL")