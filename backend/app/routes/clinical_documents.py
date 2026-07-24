from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import UPLOAD_CLINICAL, VIEW_CLINICAL
from app.auth.scoping import can_read_clinical
from app.database import get_db
from app.models.clinical_document import ClinicalDocType
from app.models.user import User
from app.schemas.clinical_document import ClinicalDocumentOut, IngestResult
from app.services import clinical_document_service
from app.services.clinical_document_service import (
    AlreadyIngestedError,
    DocumentNotFoundError,
    EmptyExtractionError,
    FileTooLargeError,
    PatientNotFoundError,
    UnsupportedFileTypeError,
)

router = APIRouter(prefix="/clinical-documents", tags=["clinical-documents"])


@router.post("", response_model=ClinicalDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_clinical_document_endpoint(
    patient_id: UUID = Form(...),
    doc_type: ClinicalDocType = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(UPLOAD_CLINICAL)),
):
    file_bytes = await file.read()
    try:
        return await clinical_document_service.upload_document(
            db,
            patient_id=patient_id,
            doc_type=doc_type,
            filename=file.filename or "upload.pdf",
            content_type=file.content_type or "application/octet-stream",
            file_bytes=file_bytes,
            actor=actor,
        )
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except EmptyExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/{document_id}/ingest", response_model=IngestResult)
async def ingest_clinical_document_endpoint(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(UPLOAD_CLINICAL)),
):
    try:
        document, chunk_count = await clinical_document_service.ingest_document(
            db, document_id, actor
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlreadyIngestedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    assert document.ingested_at is not None  # ingest_document always sets this before returning
    return IngestResult(
        document_id=document.id, chunk_count=chunk_count, ingested_at=document.ingested_at
    )


@router.get("/{document_id}/file")
async def download_clinical_document_endpoint(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_CLINICAL)),
):
    document = await clinical_document_service.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not await can_read_clinical(db, actor, document.patient_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted to read clinical records for this patient",
        )

    file_bytes = await clinical_document_service.download_document_bytes(document)
    return Response(content=file_bytes, media_type=document.content_type)
