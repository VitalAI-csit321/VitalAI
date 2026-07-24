from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token
from app.models.user import UserRole
from app.rag.retrieval import RetrievalContext, retrieve
from app.services.clinical_document_service import MAX_UPLOAD_SIZE_BYTES
from tests.pdf_fixtures import make_image_only_pdf, make_text_layer_pdf


def _upload_files(pdf_bytes: bytes, filename: str = "note.pdf"):
    return {"file": (filename, pdf_bytes, "application/pdf")}


def _pg_headers(user) -> dict:
    token = create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


# --- Upload: SQLite-backed `client` is fine here, the upload endpoint never
# --- touches the Chunk/pgvector table. MinIO must still be running.


async def test_upload_denied_without_upload_clinical_permission(
    client: AsyncClient, front_desk_headers: dict, patient
):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf()),
        headers=front_desk_headers,
    )
    assert response.status_code == 403


async def test_upload_denied_without_auth(client: AsyncClient, patient):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf()),
    )
    assert response.status_code == 401


async def test_upload_rejects_unknown_patient(client: AsyncClient, operator_headers: dict):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(uuid4()), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf()),
        headers=operator_headers,
    )
    assert response.status_code == 404


async def test_upload_rejects_oversized_file(client: AsyncClient, operator_headers: dict, patient):
    oversized = b"0" * (MAX_UPLOAD_SIZE_BYTES + 1)
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files={"file": ("huge.pdf", oversized, "application/pdf")},
        headers=operator_headers,
    )
    assert response.status_code == 413


async def test_upload_rejects_non_pdf_file(client: AsyncClient, operator_headers: dict, patient):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files={"file": ("note.txt", b"not a pdf", "text/plain")},
        headers=operator_headers,
    )
    assert response.status_code == 415


async def test_upload_rejects_corrupt_pdf_with_spoofed_content_type(
    client: AsyncClient, operator_headers: dict, patient
):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files={"file": ("fake.pdf", b"not a real pdf, just garbage", "application/pdf")},
        headers=operator_headers,
    )
    assert response.status_code == 422


async def test_upload_rejects_image_only_pdf(client: AsyncClient, operator_headers: dict, patient):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files=_upload_files(make_image_only_pdf()),
        headers=operator_headers,
    )
    assert response.status_code == 422


async def test_upload_succeeds_for_text_layer_pdf(
    client: AsyncClient, operator_headers: dict, patient
):
    response = await client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf("Blood pressure 118/76, patient stable.")),
        headers=operator_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["doc_type"] == "consultation"
    assert body["ingested_at"] is None


# --- Ingest and download need real Postgres+pgvector -> pg_client.


async def test_ingest_denied_without_upload_clinical_permission(
    pg_client: AsyncClient, pg_patient, pg_make_user
):
    uploader = await pg_make_user(UserRole.OPERATOR, "route-uploader1@example.com")
    front_desk = await pg_make_user(UserRole.FRONT_DESK, "route-frontdesk1@example.com")

    upload_response = await pg_client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(pg_patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf()),
        headers=_pg_headers(uploader),
    )
    document_id = upload_response.json()["id"]

    response = await pg_client.post(
        f"/api/v1/clinical-documents/{document_id}/ingest",
        headers=_pg_headers(front_desk),
    )
    assert response.status_code == 403


async def test_ingest_returns_404_for_unknown_document(pg_client: AsyncClient, pg_make_user):
    operator = await pg_make_user(UserRole.OPERATOR, "route-uploader2@example.com")
    response = await pg_client.post(
        f"/api/v1/clinical-documents/{uuid4()}/ingest",
        headers=_pg_headers(operator),
    )
    assert response.status_code == 404


async def test_ingest_rejects_double_ingest(pg_client: AsyncClient, pg_patient, pg_make_user):
    operator = await pg_make_user(UserRole.OPERATOR, "route-uploader3@example.com")
    upload_response = await pg_client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(pg_patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf("Second note, all vitals normal.")),
        headers=_pg_headers(operator),
    )
    document_id = upload_response.json()["id"]

    first = await pg_client.post(
        f"/api/v1/clinical-documents/{document_id}/ingest", headers=_pg_headers(operator)
    )
    assert first.status_code == 200

    second = await pg_client.post(
        f"/api/v1/clinical-documents/{document_id}/ingest", headers=_pg_headers(operator)
    )
    assert second.status_code == 409


async def test_upload_and_ingest_chunk_is_retrievable(
    pg_client: AsyncClient, pg_session: AsyncSession, pg_patient, pg_make_user
):
    operator = await pg_make_user(UserRole.OPERATOR, "route-uploader4@example.com")

    upload_response = await pg_client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(pg_patient.id), "doc_type": "consultation"},
        files=_upload_files(
            make_text_layer_pdf("Patient has a persistent dry cough and mild fever.")
        ),
        headers=_pg_headers(operator),
    )
    assert upload_response.status_code == 201
    document_id = upload_response.json()["id"]

    ingest_response = await pg_client.post(
        f"/api/v1/clinical-documents/{document_id}/ingest", headers=_pg_headers(operator)
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json()["chunk_count"] > 0

    ctx = RetrievalContext(
        patient_id=pg_patient.id, allowed_scopes=["general", "restricted"], role="operator"
    )
    results = await retrieve(pg_session, "persistent dry cough", ctx, k=5)

    assert any(r.source_document_id == UUID(document_id) for r in results)


async def test_download_denied_for_uploader_without_view_clinical(
    pg_client: AsyncClient, pg_patient, pg_make_user
):
    operator = await pg_make_user(UserRole.OPERATOR, "route-uploader5@example.com")

    upload_response = await pg_client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(pg_patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf("Uploader should not auto-see this.")),
        headers=_pg_headers(operator),
    )
    document_id = upload_response.json()["id"]

    response = await pg_client.get(
        f"/api/v1/clinical-documents/{document_id}/file", headers=_pg_headers(operator)
    )
    assert response.status_code == 403


async def test_download_denied_for_unassigned_doctor(
    pg_client: AsyncClient, pg_patient, pg_make_user
):
    operator = await pg_make_user(UserRole.OPERATOR, "route-uploader6@example.com")
    doctor = await pg_make_user(UserRole.DOCTOR, "route-doctor1@example.com")

    upload_response = await pg_client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(pg_patient.id), "doc_type": "consultation"},
        files=_upload_files(make_text_layer_pdf("Unassigned doctor should not see this.")),
        headers=_pg_headers(operator),
    )
    document_id = upload_response.json()["id"]

    response = await pg_client.get(
        f"/api/v1/clinical-documents/{document_id}/file", headers=_pg_headers(doctor)
    )
    assert response.status_code == 403


async def test_download_returns_file_bytes_for_assigned_doctor(
    pg_client: AsyncClient, pg_patient, pg_make_user
):
    operator = await pg_make_user(UserRole.OPERATOR, "route-uploader7@example.com")
    doctor = await pg_make_user(UserRole.DOCTOR, "route-doctor2@example.com")
    admin = await pg_make_user(UserRole.ADMIN, "route-admin1@example.com")

    await pg_client.post(
        "/api/v1/assignments",
        json={"doctor_id": str(doctor.id), "patient_id": str(pg_patient.id)},
        headers=_pg_headers(admin),
    )

    pdf_bytes = make_text_layer_pdf("Downloadable content check.")
    upload_response = await pg_client.post(
        "/api/v1/clinical-documents",
        data={"patient_id": str(pg_patient.id), "doc_type": "consultation"},
        files=_upload_files(pdf_bytes),
        headers=_pg_headers(operator),
    )
    document_id = upload_response.json()["id"]

    response = await pg_client.get(
        f"/api/v1/clinical-documents/{document_id}/file", headers=_pg_headers(doctor)
    )
    assert response.status_code == 200
    assert response.content == pdf_bytes
