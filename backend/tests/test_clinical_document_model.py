from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.clinical_document import ClinicalDocType, ClinicalDocument
from app.models.patient import Gender, Patient, PatientStatus
from app.models.user import User, UserRole


async def test_clinical_document_persists_with_extracted_text(db_session: AsyncSession):
    patient = Patient(
        mrn="MRN-CD000001",
        name="Doc Owner",
        dob=date(1980, 1, 1),
        gender=Gender.FEMALE,
        status=PatientStatus.ACTIVE,
    )
    uploader = User(
        email="cd-uploader@example.com",
        hashed_password=hash_password("password123"),
        full_name="Uploader",
        role=UserRole.OPERATOR,
    )
    db_session.add_all([patient, uploader])
    await db_session.flush()

    document = ClinicalDocument(
        patient_id=patient.id,
        doc_type=ClinicalDocType.CONSULTATION,
        filename="note.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_key=f"clinical-documents/{patient.id}/{uuid4()}.pdf",
        extracted_text="Blood pressure 120/80.",
        uploaded_by=uploader.id,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)

    assert document.id is not None
    assert document.ingested_at is None
    assert document.doc_type == ClinicalDocType.CONSULTATION
    assert document.extracted_text == "Blood pressure 120/80."
