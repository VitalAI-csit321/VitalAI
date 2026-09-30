import pytest
from sqlalchemy.exc import IntegrityError

from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.user import UserRole
from app.services import settings_service


async def _episode(db, patient) -> Episode:
    episode = Episode(patient_id=patient.id, title="Asthma review", status=EpisodeStatus.OPEN)
    db.add(episode)
    await db.commit()
    return episode


def _close_item(episode, status=TaskStatus.PENDING) -> HumanReviewTask:
    # A "Close this case?" item is about the case, not a message: no contact.
    return HumanReviewTask(
        case_id=None,
        episode_id=episode.id,
        task_type=TaskType.CASE_CLOSE,
        target_role=UserRole.DOCTOR,
        status=status,
    )


async def test_an_episode_starts_open_with_activity(db_session, patient):
    episode = await _episode(db_session, patient)
    await db_session.refresh(episode)
    assert episode.status == EpisodeStatus.OPEN
    assert episode.last_activity_at is not None and episode.opened_at is not None


async def test_one_open_item_per_episode_and_kind(db_session, patient):
    episode = await _episode(db_session, patient)
    first = _close_item(episode)
    db_session.add(first)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_close_item(episode))

    first.status = TaskStatus.COMPLETED
    await db_session.commit()
    db_session.add(_close_item(episode))
    await db_session.commit()  # a closed item no longer blocks a new one


def test_case_close_nudge_days_is_an_editable_setting():
    spec = settings_service.SETTINGS_REGISTRY["case_close_nudge_days"]
    assert spec.editable and spec.type is int
