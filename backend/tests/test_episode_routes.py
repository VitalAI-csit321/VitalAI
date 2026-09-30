"""The /cases API (M4 spec sections 5 and 6) and the case data other screens read."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models.appointment import Appointment, AppointmentStatus
from app.models.assignment import DoctorPatientAssignment
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.patient import Patient
from app.models.task import TaskCategory
from app.models.user import UserRole
from tests.review_helpers import assign, inbox_task

URL = "/api/v1/cases"


async def _case(db, patient, title="Asthma review", **extra) -> Episode:
    extra.setdefault("status", EpisodeStatus.OPEN)
    episode = Episode(patient_id=patient.id, title=title, **extra)
    db.add(episode)
    await db.commit()
    return episode


async def _other_patient(db) -> Patient:
    other = Patient(mrn=f"MRN-O{uuid4().hex[:6]}", name="Other Person")
    db.add(other)
    await db.commit()
    return other


async def test_front_desk_opens_renames_closes_and_reopens_a_case(
    client, front_desk_headers, patient, doctor_user, db_session
):
    await assign(db_session, doctor_user, patient)
    created = await client.post(
        URL, json={"patient_id": str(patient.id), "title": "Knee pain"}, headers=front_desk_headers
    )
    assert created.status_code == 201
    body = created.json()
    assert (body["title"], body["status"], body["doctor_id"], body["doctor_name"]) == (
        "Knee pain",
        "open",
        str(doctor_user.id),
        doctor_user.full_name,
    )
    case_url = f"{URL}/{body['id']}"

    renamed = await client.patch(
        case_url, json={"title": "Knee pain referral"}, headers=front_desk_headers
    )
    assert renamed.json()["title"] == "Knee pain referral"
    closed = await client.post(
        f"{case_url}/close", json={"note": "Referred"}, headers=front_desk_headers
    )
    assert (closed.json()["status"], closed.json()["outcome_note"]) == ("closed", "Referred")
    reopened = await client.post(f"{case_url}/reopen", json={}, headers=front_desk_headers)
    assert reopened.json()["status"] == "open"


async def test_closing_without_a_note_is_refused(client, front_desk_headers, patient, db_session):
    episode = await _case(db_session, patient)
    response = await client.post(
        f"{URL}/{episode.id}/close", json={"note": " "}, headers=front_desk_headers
    )
    assert response.status_code == 422


async def test_a_case_for_a_provisional_patient_is_refused(
    client, front_desk_headers, patient, db_session
):
    patient.is_provisional = True
    await db_session.commit()
    response = await client.post(
        URL, json={"patient_id": str(patient.id), "title": "x"}, headers=front_desk_headers
    )
    assert response.status_code == 422


async def test_a_doctor_sees_only_their_patients_cases(
    client, doctor_headers, doctor_user, patient, db_session
):
    await assign(db_session, doctor_user, patient)
    mine = await _case(db_session, patient)
    theirs = await _case(db_session, await _other_patient(db_session), title="Not mine")

    listed = (await client.get(URL, headers=doctor_headers)).json()
    assert [c["id"] for c in listed["items"]] == [str(mine.id)]
    assert (await client.get(f"{URL}/{theirs.id}", headers=doctor_headers)).status_code == 404
    closed = await client.post(
        f"{URL}/{theirs.id}/close", json={"note": "x"}, headers=doctor_headers
    )
    assert closed.status_code == 404


async def test_a_doctor_opens_a_case_only_for_their_own_patient(
    client, doctor_headers, doctor_user, patient, db_session
):
    other = await _other_patient(db_session)
    refused = await client.post(
        URL, json={"patient_id": str(other.id), "title": "x"}, headers=doctor_headers
    )
    assert refused.status_code == 404
    await assign(db_session, doctor_user, patient)
    allowed = await client.post(
        URL, json={"patient_id": str(patient.id), "title": "x"}, headers=doctor_headers
    )
    assert allowed.status_code == 201


async def test_list_filters_by_patient_and_status(client, operator_headers, patient, db_session):
    open_case = await _case(db_session, patient)
    await _case(db_session, patient, title="Done", status=EpisodeStatus.CLOSED)
    await _case(db_session, await _other_patient(db_session))
    listed = (
        await client.get(
            URL, params={"patient_id": str(patient.id), "status": "open"}, headers=operator_headers
        )
    ).json()
    assert [c["id"] for c in listed["items"]] == [str(open_case.id)]


async def test_the_case_page_shows_everything_in_the_case_newest_first(
    client, admin_headers, patient, doctor_user, db_session
):
    episode = await _case(db_session, patient)
    task = await inbox_task(db_session, category=TaskCategory.RESULTS_ENQUIRY, patient=patient)
    contact = await db_session.get(IntakeCase, task.case_id)
    contact.episode_id = episode.id
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Appointment(
                case_id=contact.id,
                doctor_id=doctor_user.id,
                time_slot=now + timedelta(days=3),
                status=AppointmentStatus.CONFIRMED,
                episode_id=episode.id,
            ),
            ConsentRecord(
                case_id=contact.id,
                status=ConsentStatus.CAPTURED,
                consent_type="treatment",
                episode_id=episode.id,
            ),
            HumanReviewTask(
                episode_id=episode.id,
                task_type=TaskType.CASE_CLOSE,
                target_role=UserRole.DOCTOR,
                status=TaskStatus.PENDING,
                notes="Close this case?",
            ),
        ]
    )
    await db_session.commit()

    body = (await client.get(f"{URL}/{episode.id}", headers=admin_headers)).json()

    kinds = [e["kind"] for e in body["timeline"]]
    assert sorted(kinds) == ["appointment", "consent", "contact", "review"]
    assert kinds[0] == "appointment"  # three days ahead: newest
    at = [e["at"] for e in body["timeline"]]
    assert at == sorted(at, reverse=True)
    (contact_row,) = [e for e in body["timeline"] if e["kind"] == "contact"]
    assert contact_row["inbox_task_id"] == str(task.id)
    assert body["patient_name"] == patient.name


async def test_set_the_case_doctor(client, operator_headers, patient, doctor_user, db_session):
    episode = await _case(db_session, patient)
    response = await client.patch(
        f"{URL}/{episode.id}", json={"doctor_id": str(doctor_user.id)}, headers=operator_headers
    )
    assert response.status_code == 200 and response.json()["doctor_id"] == str(doctor_user.id)
    assert await db_session.get(DoctorPatientAssignment, (doctor_user.id, patient.id)) is not None


async def test_the_staff_contact_endpoint_reuses_or_creates(
    client, front_desk_headers, patient, db_session
):
    episode = await _case(db_session, patient)
    first = await client.post(
        f"{URL}/{episode.id}/contact",
        json={"reason": "Booked by staff"},
        headers=front_desk_headers,
    )
    assert first.status_code == 200
    assert (first.json()["contact_channel"], first.json()["episode_id"]) == (
        "staff",
        str(episode.id),
    )
    again = await client.post(
        f"{URL}/{episode.id}/contact",
        json={"reason": "Consent captured by staff"},
        headers=front_desk_headers,
    )
    assert again.json()["id"] == first.json()["id"]

    episode.status = EpisodeStatus.CLOSED
    await db_session.commit()
    closed = await client.post(
        f"{URL}/{episode.id}/contact", json={"reason": "x"}, headers=front_desk_headers
    )
    assert closed.status_code == 409


async def test_a_cross_patient_move_is_refused_and_the_refusal_is_kept(
    client, operator_headers, patient, db_session
):
    task = await inbox_task(db_session, category=TaskCategory.RESULTS_ENQUIRY, patient=patient)
    theirs = await _case(db_session, await _other_patient(db_session))

    response = await client.post(
        f"{URL}/move",
        json={"kind": "contact", "item_id": str(task.case_id), "target_episode_id": str(theirs.id)},
        headers=operator_headers,
    )

    assert response.status_code == 409
    refusals = (
        await db_session.scalars(select(AuditEvent).where(AuditEvent.action == "case.move_refused"))
    ).all()
    assert len(refusals) == 1


async def test_move_a_contact_into_a_new_case(client, operator_headers, patient, db_session):
    task = await inbox_task(db_session, category=TaskCategory.RESULTS_ENQUIRY, patient=patient)
    response = await client.post(
        f"{URL}/move",
        json={"kind": "contact", "item_id": str(task.case_id), "new_title": "Blood results"},
        headers=operator_headers,
    )
    assert response.status_code == 200 and response.json()["title"] == "Blood results"
    contact = await db_session.get(IntakeCase, task.case_id)
    await db_session.refresh(contact)
    assert str(contact.episode_id) == response.json()["id"]


async def test_the_inbox_message_carries_the_case_chip(client, admin_headers, patient, db_session):
    episode = await _case(db_session, patient)
    task = await inbox_task(db_session, category=TaskCategory.RESULTS_ENQUIRY, patient=patient)
    contact = await db_session.get(IntakeCase, task.case_id)
    contact.episode_id = episode.id
    await db_session.commit()

    body = (await client.get(f"/api/v1/inbox/{task.id}", headers=admin_headers)).json()

    assert (body["patientId"], body["episodeId"], body["episodeTitle"]) == (
        str(patient.id),
        str(episode.id),
        "Asthma review",
    )


async def test_a_contact_shows_its_case(client, admin_headers, patient, db_session):
    episode = await _case(db_session, patient)
    contact = IntakeCase(
        patient_id=patient.id, contact_reason="x", contact_channel="staff", episode_id=episode.id
    )
    db_session.add(contact)
    await db_session.commit()
    body = (await client.get(f"/api/v1/intake/{contact.id}", headers=admin_headers)).json()
    assert body["episode_id"] == str(episode.id)
