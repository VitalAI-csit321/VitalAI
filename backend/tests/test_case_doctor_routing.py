"""Doctor work for a message in a case goes to the case's doctor, falling back
to the patient's doctor (M4 spec section 5, R5 in the plan)."""

from uuid import uuid4

from sqlalchemy import delete

from app.models.assignment import DoctorPatientAssignment
from app.models.case import IntakeCase
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import TaskType
from app.models.task import TaskCategory
from app.models.user import User, UserRole
from app.services import episode_service, inbox_service, review_routing
from tests.review_helpers import assign, inbox_task


async def _doctor(db, label: str) -> User:
    doctor = User(
        email=f"{label}-{uuid4().hex[:6]}@example.com",
        hashed_password="h",
        full_name=f"Dr {label}",
        role=UserRole.DOCTOR,
    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)  # loads permission_grants, which the inbox scope reads
    return doctor


async def _setup(db, patient, doctor_user, admin_user):
    """The patient's doctor is doctor_user; the case's doctor is someone else."""
    await assign(db, doctor_user, patient)
    specialist = await _doctor(db, "specialist")
    task = await inbox_task(db, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    episode = Episode(patient_id=patient.id, title="Asthma review", status=EpisodeStatus.OPEN)
    db.add(episode)
    await db.flush()
    await episode_service.set_doctor(db, episode, specialist.id, actor=admin_user)
    contact = await db.get(IntakeCase, task.case_id)
    contact.episode_id = episode.id
    await db.commit()
    return task, episode, specialist


async def _sees(db, doctor, task) -> bool:
    return task.id in {t.id for t in await inbox_service._visible_tasks(db, doctor)}


async def test_a_held_draft_in_a_case_goes_to_the_case_doctor(
    db_session, patient, doctor_user, admin_user
):
    task, _, specialist = await _setup(db_session, patient, doctor_user, admin_user)
    item = await review_routing.open_item(
        db_session, kind=TaskType.DRAFT_APPROVAL, inbox_task=task, reason="r", actor=None
    )
    assert (item.target_role, item.assigned_to) == (UserRole.DOCTOR, specialist.id)


async def test_the_case_doctor_sees_the_message_and_the_patients_doctor_does_not(
    db_session, patient, doctor_user, admin_user
):
    task, _, specialist = await _setup(db_session, patient, doctor_user, admin_user)
    assert await _sees(db_session, specialist, task)
    assert not await _sees(db_session, doctor_user, task)


async def test_a_case_doctor_no_longer_assigned_hands_back_to_the_patients_doctor(
    db_session, patient, doctor_user, admin_user
):
    task, _, specialist = await _setup(db_session, patient, doctor_user, admin_user)
    await db_session.execute(
        delete(DoctorPatientAssignment).where(DoctorPatientAssignment.doctor_id == specialist.id)
    )
    await db_session.commit()

    assert await _sees(db_session, doctor_user, task)
    assert not await _sees(db_session, specialist, task)
    item = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_HANDOVER, inbox_task=task, reason="r", actor=None
    )
    assert item.assigned_to == doctor_user.id


async def test_a_message_outside_any_case_keeps_every_assigned_doctor(
    db_session, patient, doctor_user
):
    second = await _doctor(db_session, "second")
    await assign(db_session, doctor_user, patient)
    await assign(db_session, second, patient)
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    assert await _sees(db_session, doctor_user, task) and await _sees(db_session, second, task)
