import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import hash_password
from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.models.chunk import Chunk
from app.models.clinical_document import ClinicalDocType, ClinicalDocument
from app.models.patient import Gender, Patient, PatientStatus
from app.models.user import User, UserRole
from app.services import clinical_document_service
from app.services.clinical_document_service import (
    AlreadyIngestedError,
    DocumentNotFoundError,
    EmptyExtractionError,
    FileTooLargeError,
    PatientNotFoundError,
    UnsupportedFileTypeError,
)
from tests.conftest import _PG_TEST_URL
from tests.pdf_fixtures import make_image_only_pdf, make_text_layer_pdf


async def test_upload_document_rejects_unknown_patient(pg_session: AsyncSession):
    uploader = User(
        email="uploader1@example.com",
        hashed_password=hash_password("password123"),
        full_name="Uploader",
        role=UserRole.OPERATOR,
    )
    pg_session.add(uploader)
    await pg_session.commit()
    await pg_session.refresh(uploader)

    with pytest.raises(PatientNotFoundError):
        await clinical_document_service.upload_document(
            pg_session,
            patient_id=uuid4(),
            doc_type=ClinicalDocType.CONSULTATION,
            filename="note.pdf",
            content_type="application/pdf",
            file_bytes=make_text_layer_pdf(),
            actor=uploader,
        )


async def test_upload_document_rejects_non_pdf_content_type(pg_session, pg_patient, pg_make_user):
    uploader = await pg_make_user(UserRole.OPERATOR, "uploader2@example.com")

    with pytest.raises(UnsupportedFileTypeError):
        await clinical_document_service.upload_document(
            pg_session,
            patient_id=pg_patient.id,
            doc_type=ClinicalDocType.CONSULTATION,
            filename="note.txt",
            content_type="text/plain",
            file_bytes=b"not a pdf",
            actor=uploader,
        )


async def test_upload_document_rejects_oversized_file(pg_session, pg_patient, pg_make_user):
    uploader = await pg_make_user(UserRole.OPERATOR, "uploader3@example.com")

    with pytest.raises(FileTooLargeError):
        await clinical_document_service.upload_document(
            pg_session,
            patient_id=pg_patient.id,
            doc_type=ClinicalDocType.CONSULTATION,
            filename="huge.pdf",
            content_type="application/pdf",
            file_bytes=b"0" * (clinical_document_service.MAX_UPLOAD_SIZE_BYTES + 1),
            actor=uploader,
        )


async def test_upload_document_rejects_corrupt_pdf_bytes(pg_session, pg_patient, pg_make_user):
    """A file claiming content_type=application/pdf but not actually parseable
    as one (corrupt, or a spoofed Content-Type header on some other file type)
    must reject cleanly, not crash: pypdf.errors.PyPdfError propagates out of
    extract_pdf_text for genuinely unreadable bytes, distinct from the "parses
    fine but has no text layer" case tested below.
    """
    uploader = await pg_make_user(UserRole.OPERATOR, "uploader4b@example.com")

    with pytest.raises(EmptyExtractionError):
        await clinical_document_service.upload_document(
            pg_session,
            patient_id=pg_patient.id,
            doc_type=ClinicalDocType.CONSULTATION,
            filename="corrupt.pdf",
            content_type="application/pdf",
            file_bytes=b"not a real pdf at all, just garbage bytes",
            actor=uploader,
        )


async def test_upload_document_rejects_image_only_pdf(pg_session, pg_patient, pg_make_user):
    uploader = await pg_make_user(UserRole.OPERATOR, "uploader4@example.com")

    with pytest.raises(EmptyExtractionError):
        await clinical_document_service.upload_document(
            pg_session,
            patient_id=pg_patient.id,
            doc_type=ClinicalDocType.CONSULTATION,
            filename="scan.pdf",
            content_type="application/pdf",
            file_bytes=make_image_only_pdf(),
            actor=uploader,
        )


async def test_upload_document_stores_text_and_logs_audit_event(
    pg_session, pg_patient, pg_make_user
):
    uploader = await pg_make_user(UserRole.OPERATOR, "uploader5@example.com")

    document = await clinical_document_service.upload_document(
        pg_session,
        patient_id=pg_patient.id,
        doc_type=ClinicalDocType.CONSULTATION,
        filename="note.pdf",
        content_type="application/pdf",
        file_bytes=make_text_layer_pdf("Patient reports mild headache, no fever."),
        actor=uploader,
    )

    assert document.id is not None
    assert document.ingested_at is None
    assert "headache" in document.extracted_text.lower()

    result = await pg_session.execute(
        select(AuditEvent).where(AuditEvent.action == "clinical_document.uploaded")
    )
    events = result.scalars().all()
    assert any(e.details.get("document_id") == str(document.id) for e in events)


async def test_ingest_document_rejects_unknown_document(pg_session, pg_make_user):
    actor = await pg_make_user(UserRole.OPERATOR, "ingester1@example.com")

    with pytest.raises(DocumentNotFoundError):
        await clinical_document_service.ingest_document(pg_session, uuid4(), actor)


async def test_ingest_document_creates_restricted_scope_chunks(
    pg_session, pg_patient, pg_make_user
):
    uploader = await pg_make_user(UserRole.OPERATOR, "ingester2@example.com")
    document = await clinical_document_service.upload_document(
        pg_session,
        patient_id=pg_patient.id,
        doc_type=ClinicalDocType.CONSULTATION,
        filename="note.pdf",
        content_type="application/pdf",
        file_bytes=make_text_layer_pdf("Patient reports mild headache, no fever." * 20),
        actor=uploader,
    )

    ingested, chunk_count = await clinical_document_service.ingest_document(
        pg_session, document.id, uploader
    )

    assert chunk_count > 0
    assert ingested.ingested_at is not None

    result = await pg_session.execute(select(Chunk).where(Chunk.source_document_id == document.id))
    chunks = result.scalars().all()
    assert len(chunks) == chunk_count
    assert all(c.access_scope == "restricted" for c in chunks)
    assert all(c.attachment_uri == f"/api/v1/clinical-documents/{document.id}/file" for c in chunks)


async def test_ingest_document_rejects_double_ingest(pg_session, pg_patient, pg_make_user):
    uploader = await pg_make_user(UserRole.OPERATOR, "ingester3@example.com")
    document = await clinical_document_service.upload_document(
        pg_session,
        patient_id=pg_patient.id,
        doc_type=ClinicalDocType.CONSULTATION,
        filename="note.pdf",
        content_type="application/pdf",
        file_bytes=make_text_layer_pdf("Second visit, blood pressure normal."),
        actor=uploader,
    )
    await clinical_document_service.ingest_document(pg_session, document.id, uploader)

    with pytest.raises(AlreadyIngestedError):
        await clinical_document_service.ingest_document(pg_session, document.id, uploader)


async def test_ingest_document_blocks_concurrent_caller_until_first_releases_lock():
    """Deterministic proof of ingest_document's with_for_update fix.

    An asyncio.gather-based "both call ingest_document at once" test was tried
    first and is NOT reliable here: get_embedding_provider()'s SentenceTransformer
    .encode() call is synchronous with no internal await, so it runs as one
    uninterrupted burst on Python's single-threaded event loop, which mostly
    (but not always, confirmed empirically: 1 failure in 5 runs against the
    pre-fix code) accidentally serializes the two calls regardless of DB
    locking, before either request reaches its blocked check. That makes it a
    flaky regression guard. This test instead holds the row lock open directly
    via a manual SELECT ... FOR UPDATE, proving (a) a concurrent ingest_document
    call genuinely blocks while the lock is held, not just "usually happens to
    go second," and (b) once unblocked it correctly sees the now-set
    ingested_at and raises AlreadyIngestedError rather than double-inserting.

    Real cross-connection test: pg_session's savepoint isolation can't prove
    this (its writes never actually commit to the base transaction, so a truly
    separate connection wouldn't see them). Uses independent, really-committed
    sessions instead, and cleans up manually afterward since nothing here rolls
    back automatically.
    """
    engine = create_async_engine(_PG_TEST_URL, echo=False)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as setup_session:
        patient = Patient(
            mrn=f"MRN-{uuid4().hex[:8].upper()}",
            name="Lock Test Patient",
            dob=date(1990, 1, 1),
            gender=Gender.FEMALE,
            status=PatientStatus.ACTIVE,
        )
        uploader = User(
            email=f"lock-uploader-{uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("password123"),
            full_name="Lock Uploader",
            role=UserRole.OPERATOR,
        )
        setup_session.add_all([patient, uploader])
        await setup_session.commit()
        await setup_session.refresh(patient)
        await setup_session.refresh(uploader)

        document = await clinical_document_service.upload_document(
            setup_session,
            patient_id=patient.id,
            doc_type=ClinicalDocType.CONSULTATION,
            filename="lock-test.pdf",
            content_type="application/pdf",
            file_bytes=make_text_layer_pdf("Lock contention test content."),
            actor=uploader,
        )
        document_id = document.id

    locking_session = async_session()
    second_session = async_session()
    try:
        locked_document = (
            await locking_session.execute(
                select(ClinicalDocument).where(ClinicalDocument.id == document_id).with_for_update()
            )
        ).scalar_one()

        second_call = asyncio.create_task(
            clinical_document_service.ingest_document(second_session, document_id, uploader)
        )

        await asyncio.sleep(0.5)
        assert not second_call.done(), (
            "second ingest_document call should still be blocked on the row lock"
        )

        locked_document.ingested_at = utcnow()
        await locking_session.commit()

        with pytest.raises(AlreadyIngestedError):
            await asyncio.wait_for(second_call, timeout=10)
    finally:
        await locking_session.close()
        await second_session.close()
        # audit_events is append-only (DB trigger blocks DELETE and, since
        # actor_id has ondelete="SET NULL", also blocks deleting the user that
        # generated one). Same as every other phase's smoke-test cleanup: the
        # user and its audit rows are left in place, everything else is not.
        async with async_session() as cleanup_session:
            await cleanup_session.execute(
                delete(Chunk).where(Chunk.source_document_id == document_id)
            )
            await cleanup_session.execute(
                delete(ClinicalDocument).where(ClinicalDocument.id == document_id)
            )
            await cleanup_session.execute(delete(Patient).where(Patient.id == patient.id))
            await cleanup_session.commit()
        await engine.dispose()
