"""Embedding provider abstraction.

Dev:  nomic-embed-text via sentence-transformers (local, no API cost)
Prod: Amazon Bedrock Titan Text Embeddings v2 (when LLM_PROVIDER=bedrock)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class NomicEmbedProvider:
    """sentence-transformers wrapper for nomic-embed-text (dev)."""

    MODEL_NAME = "nomic-ai/nomic-embed-text-v1"
    # nomic-embed-text-v1 natively outputs 768-dim vectors; this project's
    # schema commits to vector(512) (see 501a476). truncate_dim slices the
    # output down to 512 at encode time so every caller gets what the column
    # actually stores. This was never exercised end to end before FR-RAG-01 —
    # a real bug fix, not a schema placeholder.
    EMBED_DIM = 512
    _model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME, trust_remote_code=True)
        return self._model

    async def embed(self, text: str) -> list[float]:
        model = self._get_model()
        result: list[float] = model.encode(text, truncate_dim=self.EMBED_DIM).tolist()
        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        result: list[list[float]] = model.encode(texts, truncate_dim=self.EMBED_DIM).tolist()
        return result


class BedrockTitanProvider:
    """Amazon Bedrock Titan Text Embeddings v2 (prod)."""

    MODEL_ID = "amazon.titan-embed-text-v2:0"

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Bedrock Titan embeddings not wired until Phase 3")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Bedrock Titan embeddings not wired until Phase 3")


def get_embedding_provider() -> EmbeddingProvider:
    if os.getenv("LLM_PROVIDER") == "bedrock":
        return BedrockTitanProvider()
    return NomicEmbedProvider()
