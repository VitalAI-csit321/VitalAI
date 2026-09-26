from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.call import CallStatus
from app.models.case import IntakeCase, IntakeStatus
from app.models.task import Task, TaskPriority
from app.services import voicemail_service, voicemail_sweep
from tests.voicemail_fakes import FakeStorage

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch, detached_sessionmaker):
    monkeypatch.setattr(voicemail_sweep, "AsyncSessionLocal", detached_sessionmaker)
    return FakeStorage().install(monkeypatch)


async def _call(db, *, status, age, urgent=False, audio=False, storage=None):
    actor = await voicemail_service.intake_actor(db)
    call = await voicemail_service.create_voicemail(
        db, from_number="+61412345678", actor=actor, status=status, urgent_pressed=urgent
    )
    if audio:
        await voicemail_service.store_audio(db, call, b"RIFF", ".wav")
    call.created_at = NOW - age
    await db.commit()
    return call


async def test_pressed_nine_then_hung_up_gets_an_urgent_task(db_session):
    call = await _call(db_session, status=CallStatus.IN_PROGRESS, age=timedelta(0), urgent=True)
    actor = await voicemail_service.intake_actor(db_session)
    task = await voicemail_service.handle_call_ended(db_session, call, actor)
    assert call.status == CallStatus.ABANDONED
    assert task.priority == TaskPriority.URGENT
    assert "pressed 9 and hung up" in task.handover_context


async def test_plain_hang_up_gets_no_task(db_session):
    call = await _call(db_session, status=CallStatus.IN_PROGRESS, age=timedelta(0))
    actor = await voicemail_service.intake_actor(db_session)
    assert await voicemail_service.handle_call_ended(db_session, call, actor) is None
    case = await db_session.get(IntakeCase, call.case_id)
    assert case.status == IntakeStatus.INCOMPLETE


async def test_ended_twice_is_a_no_op(db_session):
    call = await _call(db_session, status=CallStatus.IN_PROGRESS, age=timedelta(0), urgent=True)
    actor = await voicemail_service.intake_actor(db_session)
    await voicemail_service.handle_call_ended(db_session, call, actor)
    assert await voicemail_service.handle_call_ended(db_session, call, actor) is None
    tasks = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalars().all()
    assert len(tasks) == 1


async def test_sweep_deletes_audio_after_30_days(db_session, storage):
    old = await _call(db_session, status=CallStatus.PROCESSED, age=timedelta(days=31), audio=True)
    new = await _call(db_session, status=CallStatus.PROCESSED, age=timedelta(days=29), audio=True)
    old_key = old.audio_key
    await voicemail_sweep.sweep_once(NOW)
    await db_session.refresh(old)
    await db_session.refresh(new)
    assert old.audio_key is None
    assert old_key not in storage.objects
    assert new.audio_key is not None


async def test_sweep_abandons_stale_live_calls_either_status(db_session, storage):
    menu = await _call(db_session, status=CallStatus.IN_PROGRESS, age=timedelta(minutes=31))
    rec = await _call(db_session, status=CallStatus.RECORDING, age=timedelta(minutes=31))
    fresh = await _call(db_session, status=CallStatus.RECORDING, age=timedelta(minutes=5))
    await voicemail_sweep.sweep_once(NOW)
    for call in (menu, rec, fresh):
        await db_session.refresh(call)
    assert menu.status == CallStatus.ABANDONED
    assert rec.status == CallStatus.ABANDONED
    assert fresh.status == CallStatus.RECORDING


async def test_sweep_reprocesses_stuck_received_calls(db_session, storage, monkeypatch):
    stuck = await _call(db_session, status=CallStatus.RECEIVED, age=timedelta(minutes=11))
    await _call(db_session, status=CallStatus.RECEIVED, age=timedelta(minutes=2))
    process = AsyncMock()
    monkeypatch.setattr(voicemail_service, "process", process)
    await voicemail_sweep.sweep_once(NOW)
    process.assert_awaited_once_with(stuck.id)


async def test_loop_waits_one_interval_before_the_first_sweep(monkeypatch):
    """Lifespan starts the loop on every app start, including the lifespan
    tests. A sweep at t=0 would hit the app engine outside any test
    transaction."""
    import asyncio

    from app.config import settings

    calls = []

    async def fake_sweep():
        calls.append(1)

    monkeypatch.setattr(voicemail_sweep, "sweep_once", fake_sweep)
    monkeypatch.setattr(settings, "voicemail_sweep_interval_seconds", 60)
    task = asyncio.create_task(voicemail_sweep.run_voicemail_sweep())
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == []


async def test_sweep_retries_failed_twilio_deletes(db_session, storage, monkeypatch):
    from app.config import settings
    from app.services import twilio_client

    monkeypatch.setattr(settings, "twilio_enabled", True)
    call = await _call(db_session, status=CallStatus.PROCESSED, age=timedelta(hours=1))
    call.twilio_recording_sid = "RE" + "4" * 32
    call.twilio_deleted = False
    await db_session.commit()
    monkeypatch.setattr(twilio_client, "delete_recording", AsyncMock(return_value=True))
    await voicemail_sweep.sweep_once(NOW)
    await db_session.refresh(call)
    assert call.twilio_deleted is True
