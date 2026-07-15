"""Seed the baseline `chunks` table with the FR-RAG-01 synthetic corpus.

SYNTHETIC DATA ONLY: see scripts/synthetic_corpus/manifest.py. BASELINE,
reconcile with Matthew's ingestion schema: this seeds the placeholder
`chunks` table (alembic/versions/0005_baseline_chunks.py)

Usage (against the docker-compose db, migrated to head):
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \\
        python -m scripts.seed_synthetic_chunks
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chunk import Chunk
from app.rag.embeddings import get_embedding_provider
from scripts.synthetic_corpus.manifest import DOCS

SYNTHETIC_PATIENT_IDS = {doc.patient_id for doc in DOCS}


async def seed(session: AsyncSession) -> int:
    """Delete any existing synthetic chunks and re-insert the corpus fresh.

    Idempotent regardless of what's already committed in `chunks`. Scoped to
    SYNTHETIC_PATIENT_IDS so this never touches real ingested data (e.g. from
    scripts/ingest_matthew_corpus.py) sharing the same table. Deleting first
    also matters for tests/conftest.py::seeded_chunks, which calls this
    inside a per-test SAVEPOINT: without the delete, a chunks table already
    populated by a prior manual `python -m scripts.seed_synthetic_chunks` run
    would double up under every test.
    """
    await session.execute(delete(Chunk).where(Chunk.patient_id.in_(SYNTHETIC_PATIENT_IDS)))
    provider = get_embedding_provider()
    inserted = 0
    for doc in DOCS:
        paragraphs = doc.read_chunks()
        embeddings = await provider.embed_documents(paragraphs)
        for index, (paragraph, embedding) in enumerate(zip(paragraphs, embeddings, strict=True)):
            session.add(
                Chunk(
                    patient_id=doc.patient_id,
                    doc_type=doc.doc_type,
                    access_scope=doc.access_scope,
                    source_document_id=doc.source_document_id,
                    citation_tag=f"{str(doc.patient_id)[:8]}_{doc.doc_type}",
                    chunk_index=index,
                    attachment_uri=None,
                    content=paragraph,
                    embedding=embedding,
                )
            )
            inserted += 1
    await session.commit()
    return inserted


async def main() -> None:
    from app.config import settings

    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        count = await seed(session)
    await engine.dispose()
    print(f"seeded {count} synthetic chunks across {len(DOCS)} documents")


if __name__ == "__main__":
    asyncio.run(main())
