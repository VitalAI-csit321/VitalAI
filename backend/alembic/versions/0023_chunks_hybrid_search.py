"""hybrid retrieval: full-text search_vector on chunks

Adds a generated tsvector column (Postgres computes and maintains it on every
insert/update, so scripts/ingest_corpus.py and scripts/ingest_org_profile.py
need no changes) plus a GIN index, so app/rag/retrieval.py can run a
Postgres full-text query alongside the existing pgvector cosine-distance
query and fuse both with Reciprocal Rank Fusion. See app/rag/retrieval.py
for the fusion logic; _security_filter is applied to both queries
independently, unchanged.

Revision ID: 0023_chunks_hybrid_search
Revises: 0022_chunks_org_wide
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023_chunks_hybrid_search"
down_revision: Union[str, None] = "0022_chunks_org_wide"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX chunks_search_vector_idx
        ON chunks
        USING gin (search_vector)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_search_vector_idx")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS search_vector")