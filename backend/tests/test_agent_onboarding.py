"""Onboarding, provisional-patient restrictions and promotion (build spec §9.0-9.0b).

Implied consent is PENDING, never CAPTURED: CAPTURED is the only status the
consent gate accepts, so recording it would let any stranger's email through.
Every restriction lives in a service, not a route. Only a human, with explicit
consent on file, turns a provisional patient into a real one.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.approval import ApprovalRequest
from app.models.case import IntakeCase
from app.models.consent import ConsentStatus
from app.models.patient import PROFILE_FIELDS, Patient, PatientStatus
from app.models.task import Task
from app.schemas.patient import PatientUpdate
from app.services import (
    appointment_service,
    assignment_service,
    clinical_document_service,
    consent_service,
    patient_service,
)
from app.services.draft_critic import critique
from app.services.patient_service import PromotionRefusedError, ProvisionalPatientError
from app.services.triage_service import ConsentGatingError, _assert_consent
from tests.agent_fakes import FakeLLM

IMPLIED = "implied_inbound_contact"
NAME, DOB = "Riley Newcomer", date(1992, 5, 17)
PHONE_REQUEST = (
    "Thank you for contacting the clinic, Riley. To finish setting up your record, "
    "please reply with a phone number we can reach you on. The rest of your "
    "registration is completed by phone or in the clinic."
)


async def _case(db) -> IntakeCase:
    case = IntakeCase(contact_reason="New patient", contact_channel="email")
    db.add(case)
    await db.commit()
    return case


@pytest.fixture
async def provisional(db_session, admin_user):
    case = await _case(db_session)
    patient = await patient_service.create_provisional_patient(
        db_session,
        case_id=case.id,
        name=NAME,
        email="riley@example.com",
        phone=None,
        dob=DOB,
        actor=admin_user,
    )
    return patient, case


# --- creation and implied consent ------------------------------------------------------


async def test_provisional_patient_links_the_case(db_session, provisional):
    patient, case = provisional

    await db_session.refresh(case)
    assert patient.is_provisional is True
    assert patient.status == PatientStatus.PENDING
    assert (patient.name, patient.dob, patient.email) == (NAME, DOB, "riley@example.com")
    assert (case.patient_id, case.patient_name) == (patient.id, NAME)


async def test_implied_consent_is_pending_and_the_consent_gate_still_refuses(
    db_session, admin_user, provisional
):
    _, case = provisional
    record = await consent_service.create_consent_record(
        db_session, case.id, admin_user, consent_type=IMPLIED
    )

    assert record.status == ConsentStatus.PENDING
    with pytest.raises(ConsentGatingError):
        await _assert_consent(db_session, case.id)


# --- restrictions, from the services ------------------------------------------------------


async def test_booking_a_provisional_patient_is_refused_by_appointment_service(
    db_session, admin_user, doctor_user, provisional
):
    _, case = provisional

    with pytest.raises(ProvisionalPatientError):
        await appointment_service.book_appointment(
            db_session,
            doctor_id=doctor_user.id,
            case_id=case.id,
            time_slot=datetime.now(UTC) + timedelta(days=3),
            actor=admin_user,
        )


async def test_booking_route_maps_the_refusal_to_409(
    client, admin_headers, doctor_user, provisional
):
    _, case = provisional

    response = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": str(doctor_user.id),
            "case_id": str(case.id),
            "time_slot": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
        headers=admin_headers,
    )

    assert response.status_code == 409, response.text


async def test_clinical_documents_of_a_provisional_patient_are_refused(db_session, provisional):
    patient, _ = provisional

    with pytest.raises(ProvisionalPatientError):
        await clinical_document_service.list_documents_for_patient(db_session, patient.id)


async def test_doctors_never_see_provisional_patients_even_when_assigned(
    client, admin_user, doctor_user, doctor_headers, admin_headers, db_session, provisional, patient
):
    new, _ = provisional
    for p in (new, patient):
        await assignment_service.assign_patient(db_session, doctor_user.id, p.id, admin_user)

    doctor_view = (await client.get("/api/v1/patients", headers=doctor_headers)).json()
    staff_view = (await client.get("/api/v1/patients", headers=admin_headers)).json()

    doctor_ids = {p["id"] for p in doctor_view["items"]}
    assert str(patient.id) in doctor_ids
    assert str(new.id) not in doctor_ids
    staff = {p["id"]: p for p in staff_view["items"]}
    assert staff[str(new.id)]["is_provisional"] is True


async def test_list_patients_excludes_provisional_by_default(db_session, provisional):
    new, _ = provisional

    hidden, _, _ = await patient_service.list_patients(db_session, limit=100)
    shown, _, _ = await patient_service.list_patients(
        db_session, limit=100, include_provisional=True
    )

    assert new.id not in {p.id for p in hidden}
    assert new.id in {p.id for p in shown}


# --- only a human promotes ----------------------------------------------------------------


def _complete_profile() -> dict:
    values = {f: "x" for f in PROFILE_FIELDS}
    values["insurance_expiry"] = date(2030, 1, 1)
    return values


async def test_a_complete_provisional_profile_stays_pending(db_session, admin_user, provisional):
    patient, _ = provisional

    await patient_service.update_patient(
        db_session, patient, PatientUpdate(gender="female", **_complete_profile()), admin_user
    )
    assert patient.status == PatientStatus.PENDING
    await patient_service.update_patient(
        db_session, patient, PatientUpdate(status=PatientStatus.ACTIVE), admin_user
    )
    assert patient.status == PatientStatus.PENDING
    assert patient.is_provisional is True


async def test_update_patient_cannot_clear_is_provisional(client, admin_headers, provisional):
    patient, _ = provisional

    response = await client.patch(
        f"/api/v1/patients/{patient.id}", json={"is_provisional": False}, headers=admin_headers
    )

    assert response.status_code in (200, 422), response.text
    assert (await client.get(f"/api/v1/patients/{patient.id}", headers=admin_headers)).json()[
        "is_provisional"
    ] is True


async def test_promotion_is_refused_with_only_implied_consent(db_session, admin_user, provisional):
    patient, case = provisional
    implied = await consent_service.create_consent_record(
        db_session, case.id, admin_user, consent_type=IMPLIED
    )
    # Even captured, implied consent is not the explicit consent promotion needs.
    await consent_service.capture_consent(db_session, implied.id, admin_user)

    with pytest.raises(PromotionRefusedError):
        await patient_service.promote_patient(db_session, patient.id, admin_user)
    await db_session.refresh(patient)
    assert patient.is_provisional is True


async def test_promotion_with_explicit_consent_is_audited(
    client, admin_headers, db_session, admin_user, provisional
):
    patient, case = provisional
    explicit = await consent_service.create_consent_record(db_session, case.id, admin_user)
    await consent_service.capture_consent(db_session, explicit.id, admin_user)

    response = await client.post(f"/api/v1/patients/{patient.id}/promote", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["is_provisional"] is False
    from app.models.audit import AuditEvent

    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "patient.promoted")
            )
        )
        .scalars()
        .all()
    )
    # Scoped to this patient: audit rows committed by another process stay.
    (event,) = [e for e in rows if e.details.get("patient_id") == str(patient.id)]
    assert event.details["before"]["is_provisional"] is True
    assert event.details["after"]["is_provisional"] is False


async def test_promotion_route_needs_register_patient(client, doctor_headers, provisional):
    patient, _ = provisional

    response = await client.post(f"/api/v1/patients/{patient.id}/promote", headers=doctor_headers)

    assert response.status_code == 403


async def test_promotion_without_consent_is_409(client, admin_headers, provisional):
    patient, _ = provisional

    response = await client.post(f"/api/v1/patients/{patient.id}/promote", headers=admin_headers)

    assert response.status_code == 409, response.text


async def test_a_purged_patient_cannot_be_promoted(db_session, admin_user, provisional):
    patient, case = provisional
    explicit = await consent_service.create_consent_record(db_session, case.id, admin_user)
    await consent_service.capture_consent(db_session, explicit.id, admin_user)
    patient.purged_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(PromotionRefusedError):
        await patient_service.promote_patient(db_session, patient.id, admin_user)


# --- the onboarding critic rule, onboarding drafts only ---------------------------------------


def test_an_onboarding_draft_asking_for_a_medicare_number_is_rejected():
    draft = "Welcome! Please reply with your Medicare number and date of birth."

    assert critique(draft, branch="onboarding") is not None


def test_a_billing_reply_mentioning_medicare_is_not_rejected():
    draft = "Our standard consultation is bulk billed for Medicare card holders."

    assert critique(draft) is None
    assert critique(draft, branch=None) is None


def test_an_onboarding_draft_asking_only_for_a_phone_passes():
    assert critique(PHONE_REQUEST, branch="onboarding") is None


# --- the demo, end to end, flag on --------------------------------------------------------


async def test_new_patient_email_is_onboarded_and_paused_for_approval(
    client, front_desk_headers, db_session, monkeypatch
):
    """Gate (g). Unknown sender, new, gives a name and DOB, wants a booking."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_reply", sends)
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))
    llm = FakeLLM(
        category="appointment_request",
        confidence=0.95,
        identity={"name": NAME, "dob": DOB.isoformat(), "phone": None},
        replies=[PHONE_REQUEST],
    )
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "riley@example.com",
            "recipient": "clinic@example.com",
            "subject": "New patient",
            "body": f"Hi, I'm new. My name is {NAME}, born 17 May 1992. "
            "I'd like to book an appointment.",
            "external_id": "AAMk-demo",
            "external_source": "outlook",
        },
        headers=front_desk_headers,
    )

    assert response.status_code == 201, response.text
    task = await db_session.get(Task, UUID(response.json()["task_id"]))
    await db_session.refresh(task)
    case = await db_session.get(IntakeCase, task.case_id)
    await db_session.refresh(case)
    # identity NO_MATCH -> provisional patient
    patient = await db_session.get(Patient, case.patient_id)
    assert patient.is_provisional is True
    assert (patient.name, patient.dob, patient.email, patient.phone) == (
        NAME,
        DOB,
        "riley@example.com",
        None,
    )
    # implied consent PENDING
    record = await consent_service.get_consent_for_case(db_session, case.id)
    assert (record.status, record.consent_type) == (ConsentStatus.PENDING, IMPLIED)
    # the draft asks for the missing phone, and only for identity/contact fields
    (prompt,) = llm.draft_prompts
    assert "phone number" in prompt.lower()
    assert "date of birth" not in prompt.lower().split("ask only for:")[1].split("\n")[0]
    # critic passed, HIGH, paused at approval, nothing sent
    approvals = [
        r
        for r in (await db_session.execute(select(ApprovalRequest))).scalars().all()
        if r.payload.get("task_id") == str(task.id)
    ]
    (approval,) = approvals
    assert approval.payload["draft"] == PHONE_REQUEST
    assert approval.payload["risk_tier"] == "high"
    assert approval.payload["reasoning"]["critic_verdict"] == "pass"
    assert task.draft_sent is False
    sends.assert_not_awaited()


async def test_onboarding_without_a_name_goes_to_staff_with_no_patient(
    client, front_desk_headers, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))
    llm = FakeLLM(category="new_patient_onboarding", identity={"dob": DOB.isoformat()})
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    before = len((await db_session.execute(select(Patient))).scalars().all())

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "anon@example.com",
            "recipient": "clinic@example.com",
            "subject": "Joining",
            "body": "I'd like to join the clinic. Born 1992-05-17.",
        },
        headers=front_desk_headers,
    )

    assert response.status_code == 201, response.text
    assert len((await db_session.execute(select(Patient))).scalars().all()) == before
    task = await db_session.get(Task, UUID(response.json()["task_id"]))
    await db_session.refresh(task)
    assert task.draft_text is None
    assert task.handover_context
    assert llm.draft_prompts == []
