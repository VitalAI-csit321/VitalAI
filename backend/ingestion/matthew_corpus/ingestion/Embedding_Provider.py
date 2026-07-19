from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol
if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------
class EmbeddingProvider(Protocol):
    """Common interface for all embedding providers."""
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:...

# ---------------------------------------------------------------------
# Local Development Provider
# ---------------------------------------------------------------------

class NomicEmbedProvider:
    """
    Local embedding model using sentence-transformers.

    Used during development.
    """

    MODEL_NAME = "nomic-ai/nomic-embed-text-v1"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model: SentenceTransformer = SentenceTransformer(
            self.MODEL_NAME,
            trust_remote_code=True,
        )

    # -----------------------------
    # Internal synchronous methods
    # -----------------------------

    def _embed_sync(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts).tolist()

    # -----------------------------
    # Public async interface
    # -----------------------------

    async def embed(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_batch_sync, texts)


# ---------------------------------------------------------------------
# Amazon Bedrock Provider
# ---------------------------------------------------------------------
class BedrockTitanProvider:
    """
    Amazon Titan Text Embeddings V2.
    Used in production.
    """
    MODEL_ID = "amazon.titan-embed-text-v2:0"

    def __init__(self) -> None:
        import boto3
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    def _embed_sync(self, text: str) -> list[float]:
        body = json.dumps(
            {
                "inputText": text,
            }
        )
        response = self.client.invoke_model(
            modelId=self.MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]
    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_sync(text) for text in texts]
    async def embed(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_batch_sync, texts)

# ---------------------------------------------------------------------
# Provider Factory
# ---------------------------------------------------------------------
_PROVIDER_MAP = {
    "local": NomicEmbedProvider,
    "bedrock": BedrockTitanProvider,
}

@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """
    Returns a singleton embedding provider.

    Environment Variables
    ---------------------
    LLM_PROVIDER

        local      -> Nomic embeddings
        bedrock    -> Titan embeddings
    """
    provider_name = os.getenv("LLM_PROVIDER", "local").lower()
    provider_cls = _PROVIDER_MAP.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown embedding provider '{provider_name}'. "
            f"Available providers: {', '.join(_PROVIDER_MAP)}"
        )
    return provider_cls()