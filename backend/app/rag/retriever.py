"""pgvector retrieval interface."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def query_similar(
    db: AsyncSession,
    embedding: list[float],
    top_k: int = 5,
    min_score: float = 0.7,
) -> list[dict[str, Any]]:
    """Return top-k chunks whose cosine similarity exceeds min_score.

    knowledge_chunks table and pgvector extension land in Phase 3.
    """
    raise NotImplementedError("pgvector retriever not implemented until Phase 3")
