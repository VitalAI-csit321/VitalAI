from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


async def embed_text(text: str) -> list[float]:
    """Return embedding vector for text using the configured provider.

    Phase 3: wire to nomic-embed-text (dev) or Bedrock Titan (prod).
    """
    raise NotImplementedError("embed_text not yet implemented")


async def store_document(
    case_id: UUID,
    text: str,
    db: AsyncSession,
) -> None:
    raise NotImplementedError("store_document not yet implemented")


async def retrieve_context(
    query: str,
    k: int = 5,
    db: AsyncSession | None = None,
) -> list[dict]:
    raise NotImplementedError("retrieve_context not yet implemented")
