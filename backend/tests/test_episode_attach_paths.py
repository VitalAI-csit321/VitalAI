"""Where a contact joins a case (M4 spec section 5, "Where attach_contact runs"),
and what appointments and consents inherit from their contact."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.case import IntakeCase
from app.models.consent import ConsentRecord
from app.models.email_conversation import EmailConversation
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.task import Task, TaskCategory
from app.models.user import UserRole
from app.schemas.email import EmailIngestRequest
from app.services import (
    appointment_service,
    consent_service,
    email_conversation_service,
    email_service,
    human_review_service,
)
from tests.agent_fakes import FakeLLM
from tests.review_helpers import inbox_task
from tests.test_agent_identity import JANE_DOB, _patient, _run


class _Classifier:
    def __init__(self, category: str):
        self.answer = json.dumps({"category": category, "confidence": 0.95})

    async def ainvoke(self, prompt: str) -> str:
        return self.answer


async def _episodes(db) -> list[Episode]:
    return list((await db.scalars(select(Episode))).all())


async def _contact(db, patient, *, channel="phone") -> IntakeCase:
    contact = IntakeCase(
        patient_id=patient.id,
        patient_name=patient.name,
        contact_reason="Visit",
        contact_channel=channel,
    )
    db.add(contact)
    await db.commit()
    return contact


async def _in_a_case(db, patient) -> tuple[IntakeCase, Episode]:
    episode = Episode(
        patient_id=patient.id,
        title="Asthma review",
        status=EpisodeStatus.OPEN,
        last_activity_at=datetime.now(UTC) - timedelta(days=10),
    )
    db.add(episode)
    await db.flush()
    contact = await _contact(db, patient)
    contact.episode_id = episode.id
    await db.commit()
    return contact, episode


# Email


async def test_flag_off_ingest_into_a_known_patients_contact_opens_a_case(
    db_session, patient, admin_user, monkeypatch
):
    contact = await _contact(db_session, patient, channel="email")
    monkeypatch.setattr(email_service, "get_llm", lambda: _Classifier("prescription_renewal"))
    payload = EmailIngestRequest(
        sender="p@example.com",
        recipient="clinic@example.com",
        subject="Repeat script please",
        body="Could I get my inhaler renewed?",
        case_id=contact.id,
    )

    await email_service.ingest_email(db_session, payload, admin_user)

    (episode,) = await _episodes(db_session)
    assert episode.title == "Repeat script please" and contact.episode_id == episode.id


async def test_a_stranger_s_clinical_email_opens_no_case(db_session, admin_user, monkeypatch):
    monkeypatch.setattr(email_service, "get_llm", lambda: _Classifier("prescription_renewal"))
    payload = EmailIngestRequest(
        sender="nobody@example.com", recipient="clinic@example.com", subject="Script", body="Hi"
    )
    await email_service.ingest_email(db_session, payload, admin_user)
    assert await _episodes(db_session) == []


async def test_the_agent_identity_match_on_a_clinical_email_opens_a_case(
    db_session, agent_saver, monkeypatch
):
    jane = await _patient(db_session, "Jane Smith", dob=JANE_DOB, email="jane@example.com")
    llm = FakeLLM(identity={"name": "Jane Smith", "dob": "1985-03-14"})

    email, _, _ = await _run(
        db_session,
        agent_saver,
        monkeypatch,
        llm,
        category=TaskCategory.RESULTS_ENQUIRY,
        sender="jane@example.com",
        body="Hi, Jane Smith here, born 14/3/1985. Are my blood results back?",
    )

    (episode,) = await _episodes(db_session)
    contact = await db_session.get(IntakeCase, email.case_id)
    await db_session.refresh(contact)
    assert (episode.patient_id, contact.episode_id) == (jane.id, episode.id)


async def test_a_general_question_from_a_known_sender_opens_no_case(
    db_session, agent_saver, monkeypatch
):
    await _patient(db_session, "Jane Smith", dob=JANE_DOB, email="jane@example.com")
    await _run(
        db_session,
        agent_saver,
        monkeypatch,
        FakeLLM(),
        category=TaskCategory.GENERAL_ADMINISTRATIVE,
        sender="jane@example.com",
    )
    assert await _episodes(db_session) == []


async def test_conversation_verification_attaches_the_contact(db_session, patient, admin_user):
    task = await inbox_task(db_session, category=TaskCategory.APPOINTMENT_REQUEST)
    conversation = EmailConversation(
        case_id=task.case_id, original_intent="appointment_request", stage="verify"
    )
    db_session.add(conversation)
    await db_session.commit()

    await email_conversation_service._link(db_session, conversation, patient, actor=admin_user)

    contact = await db_session.get(IntakeCase, task.case_id)
    (episode,) = await _episodes(db_session)
    assert contact.episode_id == episode.id


# Calls (R3: a logged call is its own contact)


def _classify_call(monkeypatch, category: str) -> None:
    monkeypatch.setattr("app.services.call_service.get_llm", lambda: _Classifier(category))


async def test_a_logged_call_for_a_chosen_patient_joins_their_case(
    client, operator_headers, db_session, patient, monkeypatch
):
    _classify_call(monkeypatch, "prescription_renewal")
    created = await client.post(
        "/api/v1/calls",
        json={"patient_id": str(patient.id), "phone_number": "0412345678", "transcript": "Script"},
        headers=operator_headers,
    )
    assert created.status_code == 201
    contact = await db_session.get(IntakeCase, UUID(created.json()["case_id"]))
    assert (contact.contact_channel, contact.patient_id) == ("call", patient.id)

    routed = await client.post(
        f"/api/v1/calls/{created.json()['id']}/route", json={}, headers=operator_headers
    )

    assert routed.status_code == 200
    await db_session.refresh(contact)
    (episode,) = await _episodes(db_session)
    assert contact.episode_id == episode.id and episode.title == "Prescription renewal"


async def test_a_logged_call_goes_into_the_case_staff_chose(
    client, operator_headers, db_session, patient, monkeypatch
):
    _, episode = await _in_a_case(db_session, patient)
    _classify_call(monkeypatch, "general_administrative")
    created = await client.post(
        "/api/v1/calls",
        json={
            "patient_id": str(patient.id),
            "episode_id": str(episode.id),
            "phone_number": "0412345678",
            "transcript": "About my asthma",
        },
        headers=operator_headers,
    )
    assert created.status_code == 201
    contact = await db_session.get(IntakeCase, UUID(created.json()["case_id"]))
    assert contact.episode_id == episode.id
    assert len(await _episodes(db_session)) == 1


async def test_a_logged_call_refuses_another_patients_case(
    client, operator_headers, db_session, patient
):
    from app.models.patient import Patient

    other = Patient(mrn="MRN-OTHER02", name="Other")
    db_session.add(other)
    await db_session.commit()
    _, theirs = await _in_a_case(db_session, other)
    response = await client.post(
        "/api/v1/calls",
        json={
            "patient_id": str(patient.id),
            "episode_id": str(theirs.id),
            "phone_number": "0412345678",
            "transcript": "x",
        },
        headers=operator_headers,
    )
    assert response.status_code == 409


async def test_a_call_with_no_patient_makes_no_case(
    client, operator_headers, db_session, monkeypatch
):
    _classify_call(monkeypatch, "prescription_renewal")
    created = await client.post(
        "/api/v1/calls",
        json={"phone_number": "0412345678", "transcript": "Script please"},
        headers=operator_headers,
    )
    assert created.status_code == 201
    await client.post(
        f"/api/v1/calls/{created.json()['id']}/route", json={}, headers=operator_headers
    )
    assert await _episodes(db_session) == []


async def test_a_caller_matched_from_the_transcript_joins_their_case(
    client, operator_headers, db_session, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "email_booking_conversation_enabled", True)
    jane = await _patient(db_session, "Jane Smith", dob=JANE_DOB, phone="0412345678")
    llm = FakeLLM(
        category="appointment_request", identity={"name": "Jane Smith", "dob": "1985-03-14"}
    )
    monkeypatch.setattr("app.services.call_service.get_llm", lambda: llm)
    created = await client.post(
        "/api/v1/calls",
        json={
            "phone_number": "0412345678",
            "transcript": "Hi, Jane Smith, born 14/3/1985. I'd like an appointment please.",
        },
        headers=operator_headers,
    )
    await client.post(
        f"/api/v1/calls/{created.json()['id']}/route", json={}, headers=operator_headers
    )

    contact = await db_session.get(IntakeCase, UUID(created.json()["case_id"]))
    await db_session.refresh(contact)
    (episode,) = await _episodes(db_session)
    assert (contact.patient_id, contact.episode_id) == (jane.id, episode.id)


# Staff confirming who it is (Review Queue identity action, F2)


async def test_linking_the_patient_on_an_identity_item_runs_the_rule(
    db_session, patient, front_desk_user
):
    task = await inbox_task(db_session, category=TaskCategory.RESULTS_ENQUIRY)
    item = HumanReviewTask(
        case_id=task.case_id,
        inbox_task_id=task.id,
        task_type=TaskType.IDENTITY_REVIEW,
        target_role=UserRole.FRONT_DESK,
        status=TaskStatus.IN_PROGRESS,
        details={"candidates": [str(patient.id)]},
    )
    db_session.add(item)
    await db_session.commit()

    await human_review_service.link_patient(db_session, item.id, front_desk_user, patient.id)

    contact = await db_session.get(IntakeCase, task.case_id)
    (episode,) = await _episodes(db_session)
    assert contact.episode_id == episode.id


# What bookings and consents inherit


async def test_a_booking_takes_its_contacts_case_and_marks_it_active(
    db_session, patient, doctor_user, admin_user
):
    contact, episode = await _in_a_case(db_session, patient)
    before = episode.last_activity_at

    appointment = await appointment_service.book_appointment(
        db_session,
        doctor_id=doctor_user.id,
        case_id=contact.id,
        time_slot=datetime(2026, 3, 3, 0, 0, tzinfo=UTC),
        actor=admin_user,
    )

    assert appointment.episode_id == episode.id and episode.last_activity_at > before


async def test_a_consent_takes_its_contacts_case_and_marks_it_active(
    db_session, patient, admin_user
):
    contact, episode = await _in_a_case(db_session, patient)
    before = episode.last_activity_at

    record = await consent_service.create_consent_record(db_session, contact.id, admin_user)

    assert record.episode_id == episode.id and episode.last_activity_at > before
    stored = await db_session.get(ConsentRecord, record.id)
    assert stored is not None and stored.episode_id == episode.id


async def test_a_contact_outside_any_case_books_outside_any_case(
    db_session, patient, doctor_user, admin_user
):
    contact = await _contact(db_session, patient)
    appointment = await appointment_service.book_appointment(
        db_session,
        doctor_id=doctor_user.id,
        case_id=contact.id,
        time_slot=datetime(2026, 3, 3, 0, 0, tzinfo=UTC),
        actor=admin_user,
    )
    assert appointment.episode_id is None
    assert (await db_session.scalars(select(Task))).all() == []  # nothing else created
