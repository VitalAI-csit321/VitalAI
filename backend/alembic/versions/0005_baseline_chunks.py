"""add baseline chunks table (FR-RAG-01)

BASELINE, reconcile with Matthew's ingestion schema. Every column shape below
(patient_id as a bare UUID with no patient entity, doc_type/access_scope as
unconstrained text, source_document_id with no documents table to reference)
is a placeholder invented to unblock vector retrieval on synthetic data. None
of it is ratified. See docs/FR-RAG-01_handoff.md for the reconciliation list.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_baseline_chunks"
down_revision: Union[str, None] = "0004_human_review_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # No CHECK constraints on doc_type / access_scope: the vocab is placeholder
    # (BASELINE, reconcile with Matthew's ingestion schema), not yet ratified.
    # patient_id is a bare UUID, not a FK — there is no separate patient entity
    # in this codebase yet (BASELINE, reconcile with Matthew's ingestion schema).
    # source_document_id is likewise a bare UUID — no documents table exists to
    # reference (BASELINE, reconcile with Matthew's ingestion schema).
    op.execute("""
        CREATE TABLE chunks (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            patient_id          UUID NOT NULL,
            doc_type            TEXT NOT NULL,
            access_scope        TEXT NOT NULL,
            source_document_id  UUID NOT NULL,
            chunk_index         INTEGER NOT NULL,
            attachment_uri      TEXT,
            content             TEXT NOT NULL,
            embedding           vector(512) NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Security filter predicates (_security_filter in app/rag/retrieval.py)
    # are patient_id == ... AND access_scope IN (...); index both together.
    op.execute("""
        CREATE INDEX chunks_patient_access_idx
        ON chunks (patient_id, access_scope)
    """)
    op.execute("""
        CREATE INDEX chunks_embedding_hnsw_idx
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chunks")
