"""add vector_store table
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_vector_store"
down_revision: Union[str, None] = "0002_triage_routed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE vector_store (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id       UUID REFERENCES intake_cases(id) ON DELETE SET NULL,
            document_text TEXT NOT NULL,
            embedding     vector(768),
            metadata      JSONB NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX vector_store_embedding_hnsw_idx
        ON vector_store
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vector_store")
