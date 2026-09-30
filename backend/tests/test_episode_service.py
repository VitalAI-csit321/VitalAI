from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.assignment import DoctorPatientAssignment
from app.models.case import IntakeCase
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.patient import Patient
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import UserRole
from app.services import episode_service
from tests.review_helpers import assign, events, inbox_task


class CaseLLM:
    """Answers the case-matching prompt; anything else is a test bug."""

    def __init__(self, answer: str | Exception):
        self.answer = answer
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def llm(monkeypatch):
    def use(answer: str | Exception = "1") -> CaseLLM:
        fake = CaseLLM(answer)
        monkeypatch.setattr(episode_service, "get_llm", lambda: fake)
        return fake

    return use


async def _contact(db, patient, category=TaskCategory.PRESCRIPTION_RENEWAL) -> IntakeCase:
    task = await inbox_task(db, category=category, patient=patient)
    contact = await db.get(IntakeCase, task.case_id)
    assert contact is not None
    return contact


async def _call_contact(db, patient, category=TaskCategory.PRESCRIPTION_RENEWAL) -> IntakeCase:
    contact = IntakeCase(
        patient_id=patient.id,
        patient_name=patient.name,
        contact_reason="Phone call",
        contact_channel="call",
    )
    db.add(contact)
    await db.flush()
    db.add(
        Task(
            case_id=contact.id,
            source=TaskSource.CALL,
            category=category,
            priority=TaskPriority.MEDIUM,
            status=TaskItemStatus.PENDING,
        )
    )
    await db.commit()
    return contact


async def _open(db, patient, title, *, active_days_ago=0) -> Episode:
    episode = Episode(
        patient_id=patient.id,
        title=title,
        status=EpisodeStatus.OPEN,
        last_activity_at=datetime.now(UTC) - timedelta(days=active_days_ago),
    )
    db.add(episode)
    await db.commit()
    return episode


async def _other_patient(db) -> Patient:
    other = Patient(mrn="MRN-OTHER01", name="Other Person")
    db.add(other)
    await db.commit()
    return other


async def _episodes(db) -> list[Episode]:
    return list((await db.scalars(select(Episode))).all())


async def _choice_items(db) -> list[HumanReviewTask]:
    return list(
        (
            await db.scalars(
                select(HumanReviewTask).where(HumanReviewTask.task_type == TaskType.CASE_CHOICE)
            )
        ).all()
    )


# The attach rule (E4)


async def test_first_clinical_message_opens_a_case_titled_from_the_subject(
    db_session, patient, doctor_user, admin_user
):
    await assign(db_session, doctor_user, patient)
    contact = await _contact(db_session, patient)

    episode = await episode_service.attach_contact(db_session, contact, actor=admin_user)

    assert episode is not None
    assert (episode.title, episode.patient_id, episode.doctor_id) == (
        "Question",  # seed_email's subject
        patient.id,
        doctor_user.id,
    )
    assert episode.status == EpisodeStatus.OPEN and episode.opened_by == admin_user.id
    assert contact.episode_id == episode.id
    (event,) = await events(db_session, "case.opened")
    assert event.details["episode_id"] == str(episode.id) and event.case_id == contact.id


async def test_a_call_is_titled_by_its_category(db_session, patient, admin_user):
    contact = await _call_contact(db_session, patient, TaskCategory.RESULTS_ENQUIRY)
    episode = await episode_service.attach_contact(db_session, contact, actor=admin_user)
    assert episode is not None and episode.title == "Results enquiry"
    assert episode.doctor_id is None  # the patient has no doctor


async def test_the_category_argument_wins_over_the_message_category(
    db_session, patient, admin_user
):
    contact = await _contact(db_session, patient, TaskCategory.GENERAL_ADMINISTRATIVE)
    episode = await episode_service.attach_contact(
        db_session, contact, actor=admin_user, category=TaskCategory.REFERRAL_REQUEST
    )
    assert episode is not None


async def test_one_open_case_takes_the_message(db_session, patient, admin_user):
    open_case = await _open(db_session, patient, "Asthma review", active_days_ago=5)
    before = open_case.last_activity_at
    contact = await _contact(db_session, patient)

    episode = await episode_service.attach_contact(db_session, contact, actor=admin_user)

    assert episode is not None and episode.id == open_case.id
    assert contact.episode_id == open_case.id
    assert open_case.last_activity_at > before
    assert len(await _episodes(db_session)) == 1
    (event,) = await events(db_session, "case.contact_attached")
    assert event.details["episode_id"] == str(open_case.id)


async def test_several_open_cases_ask_the_patients_doctor_which_one(
    db_session, patient, doctor_user, admin_user, llm
):
    await assign(db_session, doctor_user, patient)
    first = await _open(db_session, patient, "Asthma review")
    second = await _open(db_session, patient, "Knee pain referral")
    fake = llm("2")
    contact = await _contact(db_session, patient)

    assert await episode_service.attach_contact(db_session, contact, actor=admin_user) is None

    assert contact.episode_id is None
    (item,) = await _choice_items(db_session)
    assert (item.target_role, item.assigned_to) == (UserRole.DOCTOR, doctor_user.id)
    assert item.case_id == contact.id and item.inbox_task_id is not None
    candidates = item.details["candidates"]
    assert set(candidates) == {str(first.id), str(second.id)}
    # The model saw the titles in candidates order and picked the second.
    assert item.details["suggested_episode_id"] == candidates[1]
    assert "Asthma review" in fake.prompts[0] and "Knee pain referral" in fake.prompts[0]


async def test_a_case_choice_without_a_doctor_goes_to_the_operator(
    db_session, patient, admin_user, llm
):
    await _open(db_session, patient, "Asthma review")
    await _open(db_session, patient, "Knee pain referral")
    llm("1")
    contact = await _contact(db_session, patient)
    await episode_service.attach_contact(db_session, contact, actor=admin_user)
    (item,) = await _choice_items(db_session)
    assert (item.target_role, item.assigned_to) == (UserRole.OPERATOR, None)


@pytest.mark.parametrize("answer", ["banana", "7", "0", RuntimeError("model down")])
async def test_a_bad_suggestion_falls_back_to_the_most_recently_active_case(
    db_session, patient, admin_user, llm, answer
):
    await _open(db_session, patient, "Old problem", active_days_ago=20)
    recent = await _open(db_session, patient, "Recent problem", active_days_ago=1)
    llm(answer)
    contact = await _contact(db_session, patient)

    await episode_service.attach_contact(db_session, contact, actor=admin_user)

    (item,) = await _choice_items(db_session)
    assert item.details["suggested_episode_id"] == str(recent.id)


async def test_a_rerun_opens_no_second_choice_item(db_session, patient, admin_user, llm):
    await _open(db_session, patient, "Asthma review")
    await _open(db_session, patient, "Knee pain referral")
    llm("1")
    contact = await _contact(db_session, patient)
    await episode_service.attach_contact(db_session, contact, actor=admin_user)
    await episode_service.attach_contact(db_session, contact, actor=admin_user)
    assert len(await _choice_items(db_session)) == 1


@pytest.mark.parametrize(
    "category",
    [
        TaskCategory.MEDICAL_RECORDS_REQUEST,
        TaskCategory.NEW_PATIENT_ONBOARDING,
        TaskCategory.BILLING_INSURANCE_ENQUIRY,
        TaskCategory.COMPLAINT_ESCALATION,
        TaskCategory.GENERAL_ADMINISTRATIVE,
    ],
)
async def test_non_clinical_messages_never_make_a_case(
    db_session, patient, admin_user, llm, category
):
    fake = llm("1")
    contact = await _contact(db_session, patient, category)
    assert await episode_service.attach_contact(db_session, contact, actor=admin_user) is None
    assert await _episodes(db_session) == [] and fake.prompts == []


async def test_an_unidentified_sender_never_makes_a_case(db_session, admin_user, llm):
    fake = llm("1")
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL)
    contact = await db_session.get(IntakeCase, task.case_id)
    assert await episode_service.attach_contact(db_session, contact, actor=admin_user) is None
    assert await _episodes(db_session) == [] and fake.prompts == []


async def test_a_provisional_patient_never_gets_a_case(db_session, patient, admin_user, llm):
    fake = llm("1")
    patient.is_provisional = True
    await db_session.commit()
    contact = await _contact(db_session, patient)
    assert await episode_service.attach_contact(db_session, contact, actor=admin_user) is None
    assert await _episodes(db_session) == [] and fake.prompts == []


async def test_a_closed_case_never_takes_a_message(db_session, patient, admin_user):
    closed = await _open(db_session, patient, "Old sprain")
    closed.status = EpisodeStatus.CLOSED
    await db_session.commit()
    contact = await _contact(db_session, patient)

    episode = await episode_service.attach_contact(db_session, contact, actor=admin_user)

    assert episode is not None and episode.id != closed.id
    assert closed.status == EpisodeStatus.CLOSED


async def test_an_attached_contact_is_touched_not_reattached(db_session, patient, admin_user):
    contact = await _contact(db_session, patient)
    episode = await episode_service.attach_contact(db_session, contact, actor=admin_user)
    assert episode is not None
    episode.last_activity_at = datetime.now(UTC) - timedelta(days=3)
    stale = episode.last_activity_at

    again = await episode_service.attach_contact(db_session, contact, actor=admin_user)

    assert again is not None and again.id == episode.id
    assert episode.last_activity_at > stale
    assert len(await _episodes(db_session)) == 1
    assert len(await events(db_session, "case.opened")) == 1


# Close, reopen, rename, doctor


async def test_closing_needs_a_note(db_session, patient, admin_user):
    episode = await _open(db_session, patient, "Asthma review")
    with pytest.raises(episode_service.EpisodeError):
        await episode_service.close(db_session, episode, note="  ", actor=admin_user)
    assert episode.status == EpisodeStatus.OPEN


async def test_close_then_reopen(db_session, patient, admin_user):
    episode = await _open(db_session, patient, "Asthma review")
    await episode_service.close(db_session, episode, note="Resolved", actor=admin_user)
    assert (episode.status, episode.outcome_note, episode.closed_by) == (
        EpisodeStatus.CLOSED,
        "Resolved",
        admin_user.id,
    )
    await episode_service.reopen(db_session, episode, actor=admin_user)
    assert episode.status == EpisodeStatus.OPEN and episode.closed_at is None
    assert [e.action for e in await events(db_session, "case.closed")] == ["case.closed"]
    assert len(await events(db_session, "case.reopened")) == 1


async def test_set_doctor_adds_the_missing_assignment(db_session, patient, doctor_user, admin_user):
    episode = await _open(db_session, patient, "Asthma review")
    await episode_service.set_doctor(db_session, episode, doctor_user.id, actor=admin_user)
    assert episode.doctor_id == doctor_user.id
    assert await db_session.get(DoctorPatientAssignment, (doctor_user.id, patient.id)) is not None
    await episode_service.set_doctor(db_session, episode, doctor_user.id, actor=admin_user)
    rows = await db_session.scalars(
        select(DoctorPatientAssignment).where(DoctorPatientAssignment.patient_id == patient.id)
    )
    assert len(rows.all()) == 1  # not added twice


async def test_set_doctor_refuses_a_non_doctor(db_session, patient, operator_user, admin_user):
    episode = await _open(db_session, patient, "Asthma review")
    with pytest.raises(episode_service.EpisodeError):
        await episode_service.set_doctor(db_session, episode, operator_user.id, actor=admin_user)


async def test_create_refuses_a_provisional_patient(db_session, patient, admin_user):
    patient.is_provisional = True
    await db_session.commit()
    with pytest.raises(episode_service.EpisodeError):
        await episode_service.create(
            db_session, patient_id=patient.id, title="Anything", actor=admin_user
        )


# Move (E4: a wrong attach is fixed by Move)


async def test_move_a_contact_to_another_case_of_the_same_patient(db_session, patient, admin_user):
    contact = await _contact(db_session, patient)
    first = await episode_service.attach_contact(db_session, contact, actor=admin_user)
    second = await _open(db_session, patient, "Knee pain referral")

    await episode_service.move(
        db_session, kind="contact", item_id=contact.id, target=second.id, actor=admin_user
    )

    assert contact.episode_id == second.id and first is not None
    (event,) = await events(db_session, "case.item_moved")
    assert event.details["to"] == str(second.id) and event.details["from"] == str(first.id)


async def test_move_to_a_new_case(db_session, patient, admin_user):
    contact = await _contact(db_session, patient)
    await episode_service.attach_contact(db_session, contact, actor=admin_user)
    moved_to = await episode_service.move(
        db_session,
        kind="contact",
        item_id=contact.id,
        target=None,
        new_title="Separate problem",
        actor=admin_user,
    )
    assert moved_to.title == "Separate problem" and contact.episode_id == moved_to.id


async def test_a_cross_patient_move_is_refused_and_audited(db_session, patient, admin_user):
    contact = await _contact(db_session, patient)
    other = await _other_patient(db_session)
    theirs = await _open(db_session, other, "Their case")

    with pytest.raises(episode_service.WrongPatientError):
        await episode_service.move(
            db_session, kind="contact", item_id=contact.id, target=theirs.id, actor=admin_user
        )

    assert contact.episode_id is None
    (event,) = await events(db_session, "case.move_refused")
    assert event.details["target"] == str(theirs.id)


async def test_moving_into_a_closed_case_is_refused(db_session, patient, admin_user):
    contact = await _contact(db_session, patient)
    closed = await _open(db_session, patient, "Old sprain")
    closed.status = EpisodeStatus.CLOSED
    await db_session.commit()
    with pytest.raises(episode_service.EpisodeClosedError):
        await episode_service.move(
            db_session, kind="contact", item_id=contact.id, target=closed.id, actor=admin_user
        )


async def test_confirming_the_caller_then_moving_links_the_patient(db_session, patient, admin_user):
    # A voicemail contact: no confirmed patient until staff say who it is.
    contact = IntakeCase(contact_reason="Voicemail", contact_channel="voicemail")
    db_session.add(contact)
    await db_session.commit()
    target = await _open(db_session, patient, "Asthma review")

    await episode_service.move(
        db_session,
        kind="contact",
        item_id=contact.id,
        target=target.id,
        actor=admin_user,
        patient_id=patient.id,
    )

    assert (contact.patient_id, contact.episode_id) == (patient.id, target.id)
    assert len(await events(db_session, "contact.patient_confirmed")) == 1


async def test_an_unconfirmed_contact_cannot_move_without_a_patient(
    db_session, patient, admin_user
):
    contact = IntakeCase(contact_reason="Voicemail", contact_channel="voicemail")
    db_session.add(contact)
    await db_session.commit()
    target = await _open(db_session, patient, "Asthma review")
    with pytest.raises(episode_service.EpisodeError):
        await episode_service.move(
            db_session, kind="contact", item_id=contact.id, target=target.id, actor=admin_user
        )


# Staff contacts for bookings and consents


async def test_staff_contact_reuses_the_cases_latest_contact(db_session, patient, admin_user):
    contact = await _contact(db_session, patient)
    episode = await episode_service.attach_contact(db_session, contact, actor=admin_user)
    assert episode is not None
    reused = await episode_service.staff_contact(
        db_session, episode, reason="Booked by staff", actor=admin_user
    )
    assert reused.id == contact.id


async def test_staff_contact_is_created_for_a_case_with_none(db_session, patient, admin_user):
    episode = await _open(db_session, patient, "Asthma review")
    created = await episode_service.staff_contact(
        db_session, episode, reason="Consent captured by staff", actor=admin_user
    )
    assert (created.contact_channel, created.contact_reason) == (
        "staff",
        "Consent captured by staff",
    )
    assert (created.patient_id, created.episode_id) == (patient.id, episode.id)


async def test_no_staff_contact_for_a_closed_case(db_session, patient, admin_user):
    episode = await _open(db_session, patient, "Asthma review")
    episode.status = EpisodeStatus.CLOSED
    with pytest.raises(episode_service.EpisodeClosedError):
        await episode_service.staff_contact(db_session, episode, reason="x", actor=admin_user)


# Choosing on a case_choice item


async def _choice(db, patient, admin_user, llm) -> tuple[HumanReviewTask, Episode, Episode]:
    first = await _open(db, patient, "Asthma review")
    second = await _open(db, patient, "Knee pain referral")
    llm("1")
    contact = await _contact(db, patient)
    await episode_service.attach_contact(db, contact, actor=admin_user)
    (item,) = await _choice_items(db)
    return item, first, second


async def test_choosing_a_candidate_attaches_and_closes_the_item(
    db_session, patient, admin_user, llm
):
    item, _, second = await _choice(db_session, patient, admin_user, llm)
    await episode_service.choose(db_session, item, second.id, actor=admin_user)
    contact = await db_session.get(IntakeCase, item.case_id)
    assert contact is not None and contact.episode_id == second.id
    assert item.status == TaskStatus.COMPLETED
    assert len(await events(db_session, "review.completed")) == 1


async def test_choosing_new_opens_a_case(db_session, patient, admin_user, llm):
    item, first, second = await _choice(db_session, patient, admin_user, llm)
    await episode_service.choose(db_session, item, None, actor=admin_user)
    contact = await db_session.get(IntakeCase, item.case_id)
    assert contact is not None and contact.episode_id not in (None, first.id, second.id)


async def test_choosing_a_case_that_was_not_offered_is_refused(
    db_session, patient, admin_user, llm
):
    item, _, _ = await _choice(db_session, patient, admin_user, llm)
    late = await _open(db_session, patient, "Opened later")
    with pytest.raises(episode_service.EpisodeError):
        await episode_service.choose(db_session, item, late.id, actor=admin_user)
    assert item.status == TaskStatus.PENDING


async def test_choosing_a_case_closed_since_is_refused(db_session, patient, admin_user, llm):
    item, first, _ = await _choice(db_session, patient, admin_user, llm)
    first.status = EpisodeStatus.CLOSED
    with pytest.raises(episode_service.EpisodeClosedError):
        await episode_service.choose(db_session, item, first.id, actor=admin_user)


async def test_filing_a_message_by_hand_settles_its_open_case_choice(
    db_session, patient, admin_user, llm
):
    # Staff used the inbox chip instead of the Review Queue: the question is answered.
    item, first, _ = await _choice(db_session, patient, admin_user, llm)
    await episode_service.move(
        db_session, kind="contact", item_id=item.case_id, target=first.id, actor=admin_user
    )
    assert item.status == TaskStatus.COMPLETED
