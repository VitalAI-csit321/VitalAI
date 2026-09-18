"""Ingest the synthetic corpus as real clinical documents, not bare chunks.

scripts/ingest_corpus.py writes Chunk rows straight from the corpus .txt
files, with no ClinicalDocument behind them. That left every demo patient's
Records page saying "No documents on file" while the RAG answered happily
from their chunks, and nothing to download or cite back to a source file.

This script renders each corpus document to a PDF and pushes it through the
same two service calls the HTTP upload path uses -- upload_document() then
ingest_document() -- so demo data and real user uploads travel one pipeline:
PDF in object storage, ClinicalDocument row, extracted text, chunks, embeddings,
and audit events for both steps. Use this instead of ingest_corpus.py for demo
patients; ingest_corpus.py remains for the org-wide profile corpus, which has
no patient to hang a document off.

Re-running a patient deletes their chunks and document rows first, so it is
idempotent in the database. It does not delete the old objects from storage
(object_storage has no delete), so repeated runs leave orphaned PDFs in the
dev MinIO bucket.
# ponytail: orphaned objects on re-run; add object_storage.delete_object if the
# dev bucket ever grows enough to matter.

Usage (against the docker-compose db + minio, migrated to head):
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
        python -m scripts.ingest_corpus_documents --limit 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import textwrap
import uuid
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chunk import Chunk
from app.models.clinical_document import ClinicalDocType, ClinicalDocument
from app.models.user import User, UserRole
from app.services import clinical_document_service

CORPUS_DIR = Path(__file__).resolve().parents[1] / "ingestion" / "matthew_corpus" / "Synth_Dataset"

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# A4 at 9pt Courier: ~95 characters across, ~66 lines down with margins.
_WRAP_COLUMNS = 95
_LINES_PER_PAGE = 66
_LEADING = 11


def render_pdf(text: str) -> bytes:
    """A born-digital PDF whose text layer extracts back to `text`.

    Courier and hard wrapping on purpose: corpus documents are column-aligned
    plain text (lab tables, vitals), and a proportional font reflows them into
    something a reader would not recognise as the same document.
    """
    lines: list[str] = []
    for raw_line in text.splitlines():
        lines.extend(textwrap.wrap(raw_line, _WRAP_COLUMNS) or [""])

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    for start in range(0, len(lines), _LINES_PER_PAGE):
        text_object = pdf.beginText(50, height - 50)
        text_object.setFont("Courier", 9)
        text_object.setLeading(_LEADING)
        for line in lines[start : start + _LINES_PER_PAGE]:
            text_object.textLine(line)
        pdf.drawText(text_object)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def patient_uuid(folder_name: str) -> uuid.UUID:
    match = _UUID_RE.search(folder_name)
    if match is None:
        raise ValueError(f"no UUID found in patient folder name: {folder_name!r}")
    return uuid.UUID(match.group(0))


def manifest_documents(patient_dir: Path) -> list[tuple[Path, str]]:
    """(file path, doc_type) for every document the generator recorded.

    Manifest only: a corpus file the generator never listed has no ratified
    doc_type, and guessing one from the filename would silently pick its
    access_scope too (app.rag.doc_scopes fails closed to restricted).
    """
    manifest_path = patient_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"{patient_dir.name} has no manifest.json")
    manifest = json.loads(manifest_path.read_text())

    by_name = {path.name: path for path in patient_dir.rglob("*.txt")}
    documents = []
    for entry in manifest.get("documents", []):
        path = by_name.get(entry["filename"])
        if path is None:
            raise FileNotFoundError(f"{patient_dir.name}: manifest lists missing {entry['filename']}")
        documents.append((path, entry["doc_type"]))
    return documents


async def ingest_patient(session: AsyncSession, patient_dir: Path, actor: User) -> int:
    patient_id = patient_uuid(patient_dir.name)
    await session.execute(delete(Chunk).where(Chunk.patient_id == patient_id))
    await session.execute(
        delete(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id)
    )
    await session.commit()

    count = 0
    for path, doc_type in manifest_documents(patient_dir):
        document = await clinical_document_service.upload_document(
            session,
            patient_id=patient_id,
            doc_type=ClinicalDocType(doc_type),
            filename=f"{path.stem}.pdf",
            content_type="application/pdf",
            file_bytes=render_pdf(path.read_text(encoding="utf-8")),
            actor=actor,
        )
        await clinical_document_service.ingest_document(session, document.id, actor)
        count += 1
    return count


async def system_actor(session: AsyncSession) -> User:
    """Uploads and ingests are audited, so they need a real actor row."""
    result = await session.execute(
        select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at).limit(1)
    )
    actor = result.scalar_one_or_none()
    if actor is None:
        raise RuntimeError("no admin user in this database to attribute the ingest to")
    return actor


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="only the first N patient folders")
    parser.add_argument("--patient", help="only folders containing this text (name or uuid)")
    args = parser.parse_args()

    from app.config import settings

    patient_dirs = sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir())
    if args.patient:
        patient_dirs = [p for p in patient_dirs if args.patient.lower() in p.name.lower()]
    if args.limit:
        patient_dirs = patient_dirs[: args.limit]
    if not patient_dirs:
        raise SystemExit("no patient folders matched")

    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    total = 0
    failures: list[tuple[str, str]] = []
    async with async_session() as session:
        actor = await system_actor(session)
        for patient_dir in patient_dirs:
            try:
                count = await ingest_patient(session, patient_dir, actor)
            except Exception as exc:  # noqa: BLE001 - one bad patient must not abort the corpus
                await session.rollback()
                failures.append((patient_dir.name, str(exc)))
                print(f"FAILED  {patient_dir.name}: {exc}")
                continue
            total += count
            print(f"ingested {count} documents for {patient_dir.name}")
    await engine.dispose()

    print()
    print(
        f"done: {len(patient_dirs) - len(failures)}/{len(patient_dirs)} patients, "
        f"{total} documents, {len(failures)} failed"
    )
    for name, err in failures:
        print(f"  - {name}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
