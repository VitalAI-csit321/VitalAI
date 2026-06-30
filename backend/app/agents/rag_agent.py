"""RAG agent."""

from __future__ import annotations

from typing import Any


async def retrieve_context(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """pgvector retrieval entry point — not yet implemented."""
    raise NotImplementedError("RAG context retrieval not implemented until Phase 3")
