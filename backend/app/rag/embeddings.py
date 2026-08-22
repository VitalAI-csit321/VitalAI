"""Embedding provider abstraction.

nomic-embed-text via sentence-transformers (local).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class EmbeddingProvider(Protocol):
    """Query and document embedding are asymmetric, not the same call twice.

    Nomic's model is trained on separate "search_query: " and "search_document: "
    prefixes, so a query and the passage it should match are encoded differently
    on purpose. Callers must use embed_query for a query and embed_documents for
    indexed text; using one for the other produces plausible-but-wrong distances,
    same failure class as an embedding dimension mismatch.
    """

    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class NomicEmbedProvider:
    """sentence-transformers wrapper for nomic-embed-text (dev)."""

    MODEL_NAME = "nomic-ai/nomic-embed-text-v1"
    # nomic-embed-text-v1 natively outputs 768-dim vectors; this project's
    # schema commits to vector(512) (see 501a476). truncate_dim slices the
    # output down to 512 at encode time so every caller gets what the column
    # actually stores. This was never exercised end to end before FR-RAG-01 —
    # a real bug fix, not a schema placeholder.
    EMBED_DIM = 512
    QUERY_PREFIX = "search_query: "
    DOCUMENT_PREFIX = "search_document: "
    _model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME, trust_remote_code=True)
        return self._model

    async def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        result: list[float] = model.encode(
            self.QUERY_PREFIX + text, truncate_dim=self.EMBED_DIM
        ).tolist()
        return result

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        prefixed = [self.DOCUMENT_PREFIX + text for text in texts]
        result: list[list[float]] = model.encode(prefixed, truncate_dim=self.EMBED_DIM).tolist()
        return result


def get_embedding_provider() -> EmbeddingProvider:
    return NomicEmbedProvider()
