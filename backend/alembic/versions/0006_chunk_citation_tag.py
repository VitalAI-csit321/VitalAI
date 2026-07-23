"""add citation_tag column to chunks (FR-RAG-01 chunk ID reconciliation)

Additive only. source_document_id remains the stable UUID machine key (joins,
dedup, delete, GOV-RETRIEVE audit references), untouched. citation_tag is a
separate, nullable, human-readable label populated at ingest time, so the
surrogate key and the citation string stop sharing one column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_chunk_citation_tag"
down_revision: Union[str, None] = "0005_baseline_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("citation_tag", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "citation_tag")
