from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from pypdf.errors import PyPdfError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.chunk import Chunk
from app.models.clinical_document import ClinicalDocType, ClinicalDocument
from app.models.patient import Patient
from app.models.user import User
from app.rag.chunking import chunk_text
from app.rag.embeddings import get_embedding_provider
from app.rag.text_extraction import extract_pdf_text
from app.services.audit_service import record_event
from app.storage import object_storage

MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024


class PatientNotFoundError(Exception):
    """Raised when patient_id doesn't reference an existing patient."""


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file's content type isn't application/pdf."""


class FileTooLargeError(Exception):
    """Raised when the uploaded file exceeds MAX_UPLOAD_SIZE_BYTES."""


class EmptyExtractionError(Exception):
    """Raised when a PDF's text layer extracts to nothing (image-only PDF)."""


class DocumentNotFoundError(Exception):
    """Raised when document_id doesn't reference an existing clinical document."""


class AlreadyIngestedError(Exception):
    """Raised when ingest is called on a document that was already ingested."""


async def upload_document(
    db: AsyncSession,
    *,
    patient_id: UUID,
    doc_type: ClinicalDocType,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    actor: User,
) -> ClinicalDocument:
    if await db.get(Patient, patient_id) is None:
        raise PatientNotFoundError(f"No patient with id {patient_id}")
    if content_type != "application/pdf":
        raise UnsupportedFileTypeError(
            f"Unsupported content type '{content_type}', only application/pdf is accepted"
        )
    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise FileTooLargeError(
            f"File is {len(file_bytes)} bytes, exceeds the {MAX_UPLOAD_SIZE_BYTES}-byte limit"
        )

    try:
        extracted_text = extract_pdf_text(file_bytes)
    except PyPdfError as exc:
        raise EmptyExtractionError(f"This file could not be read as a valid PDF: {exc}") from exc
    if not extracted_text:
        raise EmptyExtractionError(
            "No extractable text found in this PDF. Image-only PDFs are not supported "
            "yet (OCR is future work, RBAC report section 14)."
        )

    document_id = uuid4()
    storage_key = f"clinical-documents/{patient_id}/{document_id}.pdf"
    await asyncio.to_thread(object_storage.put_object, storage_key, file_bytes, content_type)

    document = ClinicalDocument(
        id=document_id,
        patient_id=patient_id,
        doc_type=doc_type,
        filename=filename,
        content_type=content_type,
        size_bytes=len(file_bytes),
        storage_key=storage_key,
        extracted_text=extracted_text,
        uploaded_by=actor.id,
    )
    db.add(document)
    await db.flush()

    await record_event(
        db,
        actor=actor,
        action="clinical_document.uploaded",
        details={
            "document_id": str(document_id),
            "patient_id": str(patient_id),
            "doc_type": doc_type.value,
            "filename": filename,
        },
    )
    await db.commit()
    await db.refresh(document)
    return document


async def ingest_document(
    db: AsyncSession, document_id: UUID, actor: User
) -> tuple[ClinicalDocument, int]:
    # with_for_update: two concurrent ingest calls on the same document must not
    # both pass the ingested_at check below and both insert a full set of chunks.
    # This blocks a second caller until the first's transaction (chunk inserts +
    # ingested_at write) commits, so it then correctly sees AlreadyIngestedError.
    document = await db.get(ClinicalDocument, document_id, with_for_update=True)
    if document is None:
        raise DocumentNotFoundError(f"No clinical document with id {document_id}")
    if document.ingested_at is not None:
        raise AlreadyIngestedError(
            f"Document {document_id} was already ingested at {document.ingested_at}"
        )

    pieces = chunk_text(document.extracted_text)
    provider = get_embedding_provider()
    embeddings = await provider.embed_documents(pieces)

    citation_tag = f"{str(document.patient_id)[:8]}_{document.doc_type.value}"
    attachment_uri = f"/api/v1/clinical-documents/{document.id}/file"
    for index, (content, embedding) in enumerate(zip(pieces, embeddings, strict=True)):
        db.add(
            Chunk(
                patient_id=document.patient_id,
                doc_type=document.doc_type.value,
                access_scope="restricted",
                source_document_id=document.id,
                citation_tag=citation_tag,
                chunk_index=index,
                attachment_uri=attachment_uri,
                content=content,
                embedding=embedding,
            )
        )

    document.ingested_at = utcnow()
    await record_event(
        db,
        actor=actor,
        action="clinical_document.ingested",
        details={
            "document_id": str(document_id),
            "patient_id": str(document.patient_id),
            "chunk_count": len(pieces),
        },
    )
    await db.commit()
    await db.refresh(document)
    return document, len(pieces)


async def get_document(db: AsyncSession, document_id: UUID) -> ClinicalDocument | None:
    return await db.get(ClinicalDocument, document_id)


async def list_documents_for_patient(db: AsyncSession, patient_id: UUID) -> list[ClinicalDocument]:
    result = await db.execute(
        select(ClinicalDocument)
        .where(ClinicalDocument.patient_id == patient_id)
        .order_by(ClinicalDocument.created_at.desc())
    )
    return list(result.scalars().all())


async def download_document_bytes(document: ClinicalDocument) -> bytes:
    return await asyncio.to_thread(object_storage.get_object, document.storage_key)
