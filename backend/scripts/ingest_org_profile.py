"""Ingester for the org-wide (non-patient) demo corpus at
"Organization Profile Review/" (clinic identity, policies/FAQ, routing rules,
staff directory, data classification, guardrails).

Each chunk gets patient_id=NULL (see alembic 0022_chunks_org_wide and
app/rag/retrieval.py::_security_filter) so it is visible from every patient's
retrieval context, still gated by access_scope like any other chunk.

doc_type comes from the leading `<!-- doc_type: X | access_scope: Y -->`
comment in each file; the file's own access_scope hint is informational only
-- DOC_TYPE_TO_SCOPE in scripts/ingest_corpus.py is the single source of
truth, same as the patient corpus.

Not ray/Loader/Cleaner/Chunker-based like ingest_corpus.py: those assume a
patient-folder directory layout (UUID in the folder name) that this flat,
6-file corpus doesn't have. The clean/chunk logic here is the same
whitespace-normalise + fixed-size character slice, just inlined.

Usage (against the docker-compose db, migrated to head):
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
        python -m scripts.ingest_org_profile
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chunk import Chunk
from app.rag.embeddings import get_embedding_provider
from scripts.ingest_corpus import CHUNK_SIZE, EMBEDDING_DIM, DOC_TYPE_TO_SCOPE

_ORG_PROFILE_DIR = Path(__file__).resolve().parents[2] / "Organization Profile Review"
_DOC_TYPE_RE = re.compile(r"<!--\s*doc_type:\s*(\w+)\s*\|")


def _load_doc(file_path: Path) -> tuple[str, str]:
    """Return (doc_type, cleaned_text). Fails loud if the front-matter comment is missing."""
    raw = file_path.read_text(encoding="utf-8")
    match = _DOC_TYPE_RE.search(raw)
    if match is None:
        raise ValueError(f"no doc_type front-matter comment found in {file_path}")
    doc_type = match.group(1)
    text = re.sub(r"\s+", " ", raw).strip()
    return doc_type, text


def _chunk(text: str, chunk_size: int) -> list[str]:
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def ingest_org_profile(session: AsyncSession) -> int:
    """Delete any existing org-wide chunks and re-insert fresh. Idempotent."""
    await session.execute(delete(Chunk).where(Chunk.patient_id.is_(None)))

    provider = get_embedding_provider()
    total = 0
    for file_path in sorted(_ORG_PROFILE_DIR.glob("0[1-6]_*.md")):
        doc_type, text = _load_doc(file_path)
        access_scope = DOC_TYPE_TO_SCOPE.get(doc_type, "restricted")
        chunk_contents = _chunk(text, CHUNK_SIZE)
        embeddings = await provider.embed_documents(chunk_contents)

        source_document_id = uuid.uuid4()
        for index, (content, embedding) in enumerate(
            zip(chunk_contents, embeddings, strict=True)
        ):
            if len(embedding) != EMBEDDING_DIM:
                raise ValueError(
                    f"embedding provider returned {len(embedding)} dims, expected "
                    f"{EMBEDDING_DIM} ({file_path})"
                )
            session.add(
                Chunk(
                    patient_id=None,
                    doc_type=doc_type,
                    access_scope=access_scope,
                    source_document_id=source_document_id,
                    citation_tag=f"org_{doc_type}",
                    chunk_index=index,
                    attachment_uri=None,
                    content=content,
                    embedding=embedding,
                )
            )
        total += len(chunk_contents)
        print(f"ingested {len(chunk_contents)} chunks for {file_path.name} (doc_type={doc_type})")

    await session.commit()
    return total


async def main() -> None:
    from app.config import settings

    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        total = await ingest_org_profile(session)
    await engine.dispose()

    print()
    print(f"done: {total} chunks total")


if __name__ == "__main__":
    asyncio.run(main())