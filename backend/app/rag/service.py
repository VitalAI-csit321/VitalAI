"""Knowledge retrieval service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


async def retrieve_knowledge(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    min_score: float = 0.7,
) -> list[RetrievedChunk]:
    """Embed query, retrieve similar chunks, return with confidence scores.

    Depends on Phase 3 pgvector migration.
    """
    raise NotImplementedError("Knowledge retrieval not implemented until Phase 3")
