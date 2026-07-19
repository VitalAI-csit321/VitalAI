"""Ingester: loader/cleaner/chunker into the real chunks table.

Walking-skeleton for FR-RAG-01. Reuses ingestion.Loader.load_document,
ingestion.Cleaner.clean_text, and ingestion.Chunker.chunk_text from "Rag Pipeline/"
unchanged, then embeds through app.rag.embeddings.get_embedding_provider(), the same
512-dim factory retrieve() uses, and inserts real Chunk rows. The corpus's own
Embedding_Provider/Storage modules are not imported; this script is the only producer
of vectors and the only writer to Postgres in this path.

Runs the full Synth_Dataset corpus (100 patients), one patient at a time, each in
its own delete-then-insert transaction so a single bad patient can't roll back
everyone else's data. Not a modification to any existing module, ingestion or app.rag.

doc_type is set to the filename stem verbatim (consultation, prescription,
pathology_report, registration_form, appointment_history). It is not mapped onto the
baseline synthetic corpus vocabulary (clinical_note, lab_result, ...); that
reconciliation is separate, open work.

access_scope comes from DOC_TYPE_TO_SCOPE below, the single source of truth for the
ratified doc_type -> access_scope mapping. The demo query in
scripts/run_ingest_demo.py-equivalent (or any manual RetrievalContext) must read
allowed_scopes from this same constant, so ingest and query cannot drift apart.

Usage (against the docker-compose db, migrated to head):
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
        python -m scripts.ingest_corpus
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

import ray
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# "Rag Pipeline/" is a sibling directory with a space in its name, not an installed
# package. Put it on sys.path so ingestion.* imports resolve without touching that
# folder's contents.
_RAG_PIPELINE_DIR = Path(__file__).resolve().parents[1] / "ingestion" / "matthew_corpus"
sys.path.insert(0, str(_RAG_PIPELINE_DIR))

from ingestion.Chunker import chunk_text  # noqa: E402
from ingestion.Cleaner import clean_text  # noqa: E402
from ingestion.Loader import load_document  # noqa: E402

from app.models.chunk import Chunk
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider

EMBEDDING_DIM = 512
# 500 chars, not the original driver's 50. Still character-based, still Chunker.chunk_text
# unchanged, just a larger size argument so a short clinical fact (a label and
# its value) lands in one chunk instead of splitting across two.
CHUNK_SIZE = 500

# Ratified access_scope vocabulary, keyed on doc_type (not folder label). The
# generator emits exactly five doc_types, confirmed by listing the dataset on disk.
# The sensitive tier stays defined in the vocabulary but no current doc_type maps to
# it, because the generator emits no sensitive document class yet. An unknown or
# unmapped doc_type fails closed to restricted, never general, so an unrecognised
# clinical document cannot leak to all staff.
DOC_TYPE_TO_SCOPE = {
    "consultation": "restricted",
    "pathology_report": "restricted",
    "prescription": "restricted",
    "registration_form": "general",
    "appointment_history": "general",
}

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _extract_patient_uuid(folder_name: str) -> uuid.UUID:
    """Pull the UUID out of the corpus's "Name_UUID" folder name. Fails loud if absent."""
    match = _UUID_RE.search(folder_name)
    if match is None:
        raise ValueError(f"no UUID found in patient folder name: {folder_name!r}")
    return uuid.UUID(match.group(0))


def _access_scope_for_doc_type(doc_type: str) -> str:
    return DOC_TYPE_TO_SCOPE.get(doc_type, "restricted")


def _list_patient_files(patient_dir: Path) -> list[Path]:
    files = []
    for root, _dirs, filenames in os.walk(patient_dir):
        for filename in filenames:
            if filename.endswith((".txt", ".pdf")):
                files.append(Path(root) / filename)
    return sorted(files)


async def ingest_file(
    session: AsyncSession, file_path: Path, provider: EmbeddingProvider
) -> int:
    """Run the loader/cleaner/chunker unchanged, then embed and insert for real."""
    raw_ref = load_document.remote(str(file_path))
    clean_ref = clean_text.remote(raw_ref)
    chunked_ref = chunk_text.remote(clean_ref, CHUNK_SIZE)
    chunked = ray.get(chunked_ref)

    patient_id = _extract_patient_uuid(chunked["patient_id"])
    doc_type = file_path.stem
    access_scope = _access_scope_for_doc_type(doc_type)
    source_document_id = uuid.uuid4()
    citation_tag = f"{str(patient_id)[:8]}_{doc_type}"

    chunk_contents = chunked["chunks"]
    embeddings = await provider.embed_documents(chunk_contents)

    for index, (content, embedding) in enumerate(zip(chunk_contents, embeddings, strict=True)):
        if len(embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"embedding provider returned {len(embedding)} dims, expected "
                f"{EMBEDDING_DIM} ({file_path})"
            )
        session.add(
            Chunk(
                patient_id=patient_id,
                doc_type=doc_type,
                access_scope=access_scope,
                source_document_id=source_document_id,
                citation_tag=citation_tag,
                chunk_index=index,
                attachment_uri=None,
                content=content,
                embedding=embedding,
            )
        )

    return len(chunk_contents)


async def ingest_patient(session: AsyncSession, patient_dir: Path) -> int:
    """Delete any existing chunks for this patient and re-insert fresh. Idempotent."""
    patient_id = _extract_patient_uuid(patient_dir.name)
    await session.execute(delete(Chunk).where(Chunk.patient_id == patient_id))

    provider = get_embedding_provider()
    total = 0
    for file_path in _list_patient_files(patient_dir):
        total += await ingest_file(session, file_path, provider)

    await session.commit()
    return total


def _list_patient_dirs(dataset_dir: Path) -> list[Path]:
    return sorted(p for p in dataset_dir.iterdir() if p.is_dir())


async def main() -> None:
    from app.config import settings

    # ray.init(local_mode=True) is not available in ray 2.56 ("no longer supported").
    ray.init(ignore_reinit_error=True, num_cpus=2)

    dataset_dir = _RAG_PIPELINE_DIR / "Synth_Dataset"
    patient_dirs = _list_patient_dirs(dataset_dir)

    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    total_chunks = 0
    failures: list[tuple[str, str]] = []
    async with async_session() as session:
        for patient_dir in patient_dirs:
            try:
                count = await ingest_patient(session, patient_dir)
            except Exception as exc:  # noqa: BLE001 - one bad patient must not abort the corpus
                await session.rollback()
                failures.append((patient_dir.name, str(exc)))
                print(f"FAILED  {patient_dir.name}: {exc}")
                continue
            total_chunks += count
            print(f"ingested {count} chunks for patient folder {patient_dir.name}")
    await engine.dispose()

    print()
    print(
        f"done: {len(patient_dirs) - len(failures)}/{len(patient_dirs)} patients ingested, "
        f"{total_chunks} chunks total, {len(failures)} failed"
    )
    if failures:
        print("failures:")
        for name, err in failures:
            print(f"  - {name}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
