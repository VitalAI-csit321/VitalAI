"""drop vector_store: created by 0003, never mapped, read or written

Revision ID: 0041_drop_vector_store
Revises: 0040_task_email_id
Create Date: 2026-10-18 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041_drop_vector_store"
down_revision: str | None = "0040_task_email_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Retrieval has used `chunks` since 0005; this table was the Sprint 1
    # placeholder and nothing in app/ or scripts/ names it.
    op.execute("DROP TABLE IF EXISTS vector_store")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE vector_store (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id       UUID REFERENCES intake_cases(id) ON DELETE SET NULL,
            document_text TEXT NOT NULL,
            embedding     vector(512),
            metadata      JSONB NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX vector_store_embedding_hnsw_idx
        ON vector_store
        USING hnsw (embedding vector_cosine_ops)
    """)
