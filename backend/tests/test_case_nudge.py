"""The close nudge and the two case items in the Review Queue (M4 spec, E4, E5)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.appointment import Appointment, AppointmentStatus
from app.models.case import IntakeCase
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.task import TaskCategory
from app.models.user import User, UserRole
from app.services import case_nudge, episode_service
from tests.review_helpers import assign, events, inbox_task


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _case(db, patient, *, idle_days=40, doctor=None, **extra) -> Episode:
    episode = Episode(
        patient_id=patient.id,
        title="Asthma review",
        status=extra.pop("status", EpisodeStatus.OPEN),
        doctor_id=doctor.id if doctor else None,
        last_activity_at=_ago(idle_days),
        **extra,
    )
    db.add(episode)
    await db.commit()
    return episode


async def _close_items(db) -> list[HumanReviewTask]:
    return list(
        (
            await db.scalars(
                select(HumanReviewTask).where(HumanReviewTask.task_type == TaskType.CASE_CLOSE)
            )
        ).all()
    )


async def _other_doctor(db) -> User:
    doctor = User(
        email=f"other-{uuid4().hex[:6]}@example.com",
        hashed_password="h",
        full_name="Dr Other",
        role=UserRole.DOCTOR,
    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


# The sweep


async def test_a_quiet_case_asks_its_doctor_to_close_it(
    db_session, patient, doctor_user, admin_user
):
    await assign(db_session, doctor_user, patient)
    episode = await _case(db_session, patient, doctor=doctor_user)

    await case_nudge.nudge_due(db_session, admin_user)

    (item,) = await _close_items(db_session)
    assert (item.episode_id, item.case_id) == (episode.id, None)
    assert (item.target_role, item.assigned_to) == (UserRole.DOCTOR, doctor_user.id)
    (event,) = await events(db_session, "review.opened")
    assert event.details["kind"] == "case_close"


async def test_a_case_without_a_doctor_asks_the_operator(db_session, patient, admin_user):
    await _case(db_session, patient)
    await case_nudge.nudge_due(db_session, admin_user)
    (item,) = await _close_items(db_session)
    assert (item.target_role, item.assigned_to) == (UserRole.OPERATOR, None)


async def test_the_sweep_asks_once(db_session, patient, admin_user):
    await _case(db_session, patient)
    await case_nudge.nudge_due(db_session, admin_user)
    await case_nudge.nudge_due(db_session, admin_user)
    assert len(await _close_items(db_session)) == 1


async def test_a_recently_active_case_is_left_alone(db_session, patient, admin_user):
    await _case(db_session, patient, idle_days=5)
    await case_nudge.nudge_due(db_session, admin_user)
    assert await _close_items(db_session) == []


async def test_a_case_with_an_upcoming_appointment_is_left_alone(
    db_session, patient, doctor_user, admin_user
):
    episode = await _case(db_session, patient)
    contact = IntakeCase(patient_id=patient.id, contact_reason="x", contact_channel="staff")
    db_session.add(contact)
    await db_session.flush()
    db_session.add(
        Appointment(
            case_id=contact.id,
            doctor_id=doctor_user.id,
            time_slot=datetime.now(UTC) + timedelta(days=7),
            status=AppointmentStatus.CONFIRMED,
            episode_id=episode.id,
        )
    )
    await db_session.commit()
    await case_nudge.nudge_due(db_session, admin_user)
    assert await _close_items(db_session) == []


async def test_a_past_or_cancelled_appointment_does_not_keep_a_case_open(
    db_session, patient, doctor_user, admin_user
):
    episode = await _case(db_session, patient)
    contact = IntakeCase(patient_id=patient.id, contact_reason="x", contact_channel="staff")
    db_session.add(contact)
    await db_session.flush()
    db_session.add_all(
        [
            Appointment(
                case_id=contact.id,
                doctor_id=doctor_user.id,
                time_slot=_ago(35),
                status=AppointmentStatus.COMPLETED,
                episode_id=episode.id,
            ),
            Appointment(
                case_id=contact.id,
                doctor_id=doctor_user.id,
                time_slot=datetime.now(UTC) + timedelta(days=3),
                status=AppointmentStatus.CANCELLED,
                episode_id=episode.id,
            ),
        ]
    )
    await db_session.commit()
    await case_nudge.nudge_due(db_session, admin_user)
    assert len(await _close_items(db_session)) == 1


async def test_a_snoozed_case_waits(db_session, patient, admin_user):
    await _case(db_session, patient, nudge_snoozed_until=datetime.now(UTC) + timedelta(days=2))
    await case_nudge.nudge_due(db_session, admin_user)
    assert await _close_items(db_session) == []


async def test_a_closed_case_is_never_asked_about(db_session, patient, admin_user):
    await _case(db_session, patient, status=EpisodeStatus.CLOSED)
    await case_nudge.nudge_due(db_session, admin_user)
    assert await _close_items(db_session) == []


async def test_the_quiet_period_is_the_setting(db_session, patient, admin_user, monkeypatch):
    await _case(db_session, patient, idle_days=12)
    await case_nudge.nudge_due(db_session, admin_user)
    assert await _close_items(db_session) == []
    monkeypatch.setattr(settings, "case_close_nudge_days", 10)
    await case_nudge.nudge_due(db_session, admin_user)
    assert len(await _close_items(db_session)) == 1


# Acting on the items


async def _nudged(db, patient, doctor, admin) -> tuple[Episode, HumanReviewTask]:
    await assign(db, doctor, patient)
    episode = await _case(db, patient, doctor=doctor)
    await case_nudge.nudge_due(db, admin)
    (item,) = await _close_items(db)
    return episode, item


async def test_close_from_the_item_closes_the_case(
    client, db_session, patient, doctor_user, doctor_headers, admin_user
):
    episode, item = await _nudged(db_session, patient, doctor_user, admin_user)
    response = await client.post(
        f"/api/v1/human-review/{item.id}/case-close",
        json={"close": True, "note": "Asthma settled"},
        headers=doctor_headers,
    )
    assert response.status_code == 200
    await db_session.refresh(episode)
    await db_session.refresh(item)
    assert (episode.status, episode.outcome_note) == (EpisodeStatus.CLOSED, "Asthma settled")
    assert item.status == TaskStatus.COMPLETED


async def test_closing_from_the_item_needs_a_note(
    client, db_session, patient, doctor_user, doctor_headers, admin_user
):
    _, item = await _nudged(db_session, patient, doctor_user, admin_user)
    response = await client.post(
        f"/api/v1/human-review/{item.id}/case-close",
        json={"close": True, "note": "   "},
        headers=doctor_headers,
    )
    assert response.status_code == 422


async def test_keep_open_snoozes_for_the_setting(
    client, db_session, patient, doctor_user, doctor_headers, admin_user, monkeypatch
):
    monkeypatch.setattr(settings, "case_close_nudge_days", 14)
    episode, item = await _nudged(db_session, patient, doctor_user, admin_user)
    response = await client.post(
        f"/api/v1/human-review/{item.id}/case-close",
        json={"close": False},
        headers=doctor_headers,
    )
    assert response.status_code == 200
    await db_session.refresh(episode)
    await db_session.refresh(item)
    snoozed = episode.nudge_snoozed_until.replace(tzinfo=UTC)
    assert timedelta(days=13) < snoozed - datetime.now(UTC) <= timedelta(days=14)
    assert episode.status == EpisodeStatus.OPEN and item.status == TaskStatus.COMPLETED
    assert len(await events(db_session, "case.kept_open")) == 1
    # Snoozed: the next sweep asks nothing.
    await case_nudge.nudge_due(db_session, admin_user)
    assert len(await _close_items(db_session)) == 1


async def test_another_doctor_cannot_close_the_case(
    client, db_session, patient, doctor_user, admin_user
):
    from app.auth.security import create_access_token

    _, item = await _nudged(db_session, patient, doctor_user, admin_user)
    other = await _other_doctor(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(other.id, other.role)}"}
    response = await client.post(
        f"/api/v1/human-review/{item.id}/case-close",
        json={"close": True, "note": "x"},
        headers=headers,
    )
    assert response.status_code == 403


async def test_the_case_doctor_sees_the_item_in_their_queue(
    client, db_session, patient, doctor_user, doctor_headers, admin_user
):
    episode, item = await _nudged(db_session, patient, doctor_user, admin_user)
    body = (await client.get("/api/v1/human-review", headers=doctor_headers)).json()
    (row,) = [r for r in body["items"] if r["id"] == str(item.id)]
    assert (row["case_title"], row["patient_name"], row["episode_id"]) == (
        "Asthma review",
        patient.name,
        str(episode.id),
    )


async def test_choose_case_route_attaches_the_message(
    client, db_session, patient, doctor_user, doctor_headers, admin_user, monkeypatch
):
    await assign(db_session, doctor_user, patient)
    first = await _case(db_session, patient, idle_days=1)
    await _case(db_session, patient, idle_days=2)

    class _LLM:
        async def ainvoke(self, prompt):
            return "1"

    monkeypatch.setattr(episode_service, "get_llm", lambda: _LLM())
    task = await inbox_task(db_session, category=TaskCategory.RESULTS_ENQUIRY, patient=patient)
    contact = await db_session.get(IntakeCase, task.case_id)
    await episode_service.attach_contact(db_session, contact, actor=admin_user)
    await db_session.commit()

    body = (await client.get("/api/v1/human-review", headers=doctor_headers)).json()
    (row,) = [r for r in body["items"] if r["task_type"] == "case_choice"]
    assert {c["title"] for c in row["case_candidates"]} == {"Asthma review"}
    assert len(row["case_candidates"]) == 2
    assert row["details"]["suggested_episode_id"] == str(first.id)

    response = await client.post(
        f"/api/v1/human-review/{row['id']}/choose-case",
        json={"episode_id": str(first.id)},
        headers=doctor_headers,
    )
    assert response.status_code == 200
    await db_session.refresh(contact)
    assert contact.episode_id == first.id


@pytest.mark.parametrize("path", ["choose-case", "case-close"])
async def test_the_case_actions_refuse_other_kinds(client, db_session, operator_headers, path):
    task = await inbox_task(db_session)
    item = HumanReviewTask(
        case_id=task.case_id,
        inbox_task_id=task.id,
        task_type=TaskType.ROUTING_REVIEW,
        target_role=UserRole.OPERATOR,
        status=TaskStatus.IN_PROGRESS,
    )
    db_session.add(item)
    await db_session.commit()
    body = {"episode_id": None} if path == "choose-case" else {"close": False}
    response = await client.post(
        f"/api/v1/human-review/{item.id}/{path}", json=body, headers=operator_headers
    )
    assert response.status_code == 409
