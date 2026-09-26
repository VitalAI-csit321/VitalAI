from datetime import date

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.audit import AuditEvent
from app.models.call import Call, CallKind, CallStatus
from app.models.task import Task, TaskCategory, TaskPriority, TaskSource
from app.services import voicemail_service
from app.services.voicemail_service import (
    create_voicemail,
    is_withheld,
    parse_keypad_dob,
    process,
    store_audio,
)
from tests.voicemail_fakes import FakeClassifier, FakeStorage, fake_transcript


@pytest.fixture(autouse=True)
def flag_off(monkeypatch):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)


@pytest.fixture
def storage(monkeypatch, detached_sessionmaker):
    monkeypatch.setattr(voicemail_service, "AsyncSessionLocal", detached_sessionmaker)
    return FakeStorage().install(monkeypatch)


@pytest.fixture
def classifier(monkeypatch):
    model = FakeClassifier()
    monkeypatch.setattr(voicemail_service, "get_llm", lambda: model)
    return model


async def _received(db, *, from_number="+61412345678", **keypad) -> Call:
    actor = await voicemail_service.intake_actor(db)
    call = await create_voicemail(
        db, from_number=from_number, actor=actor, status=CallStatus.RECEIVED, **keypad
    )
    await store_audio(db, call, b"RIFF", ".wav")
    return call


async def _task(db, call: Call) -> Task:
    return (await db.execute(select(Task).where(Task.call_id == call.id))).scalar_one()


@pytest.mark.parametrize(
    ("value", "withheld"),
    [
        ("+61412345678", False),
        ("0412345678", False),
        ("anonymous", True),
        ("unknown", True),
        ("+266696687", True),  # Twilio's legacy ANONYMOUS placeholder
        ("", True),
        (None, True),
    ],
)
def test_is_withheld(value, withheld):
    assert is_withheld(value) is withheld


@pytest.mark.parametrize(
    ("digits", "expected"),
    [
        ("03071985", date(1985, 7, 3)),
        ("030785", None),  # six digits
        ("31021985", None),  # 31 February
        ("01012099", None),  # future
        ("", None),
        (None, None),
        ("0307198a", None),
    ],
)
def test_parse_keypad_dob(digits, expected):
    assert parse_keypad_dob(digits, today=date(2026, 9, 26)) == expected


async def test_create_voicemail_is_idempotent_on_sid(db_session):
    actor = await voicemail_service.intake_actor(db_session)
    sid = "CA" + "a" * 32
    first = await create_voicemail(
        db_session, from_number="+61412345678", actor=actor, call_sid=sid
    )
    again = await create_voicemail(
        db_session, from_number="+61412345678", actor=actor, call_sid=sid
    )
    assert first.id == again.id
    assert first.kind == CallKind.VOICEMAIL
    assert first.status == CallStatus.IN_PROGRESS


async def test_withheld_number_is_stored_as_withheld(db_session):
    actor = await voicemail_service.intake_actor(db_session)
    call = await create_voicemail(db_session, from_number="anonymous", actor=actor)
    assert call.phone_number == voicemail_service.WITHHELD


async def test_process_classifies_and_creates_task(db_session, storage, classifier, monkeypatch):
    classifier.category = "billing_insurance_enquiry"
    fake_transcript(monkeypatch, "Hi, I have a question about my bill.")
    call = await _received(db_session)
    await process(call.id)
    await db_session.refresh(call)
    task = await _task(db_session, call)
    assert call.status == CallStatus.PROCESSED
    assert call.transcript == "Hi, I have a question about my bill."
    assert call.transcript_quality["low"] is False
    assert task.source == TaskSource.CALL
    assert task.category == TaskCategory.BILLING_INSURANCE_ENQUIRY
    assert task.priority != TaskPriority.URGENT


async def test_keypad_intent_wins_over_classifier(db_session, storage, classifier, monkeypatch):
    classifier.category = "general_administrative"
    fake_transcript(monkeypatch, "Can I come in next week?")
    call = await _received(db_session, keypad_intent="appointment")
    await process(call.id)
    assert (await _task(db_session, call)).category == TaskCategory.APPOINTMENT_REQUEST


async def test_classifier_emergency_beats_keypad(db_session, storage, classifier, monkeypatch):
    classifier.category = "urgent_emergency"
    fake_transcript(monkeypatch, "My father collapsed and is not responding.")
    call = await _received(db_session, keypad_intent="appointment")
    await process(call.id)
    task = await _task(db_session, call)
    assert task.category == TaskCategory.URGENT_EMERGENCY
    assert task.priority == TaskPriority.URGENT
    assert task.handover_context.startswith("URGENT voicemail")


async def test_pressed_nine_is_urgent_whatever_the_words(
    db_session, storage, classifier, monkeypatch
):
    fake_transcript(monkeypatch, "Please call me back about my results.")
    call = await _received(db_session, urgent_pressed=True, keypad_intent="results")
    await process(call.id)
    task = await _task(db_session, call)
    assert task.priority == TaskPriority.URGENT
    assert "caller pressed 9" in task.handover_context
    assert "+61412345678" in task.handover_context


async def test_low_quality_skips_classifier_but_keywords_still_count(
    db_session, storage, classifier, monkeypatch
):
    fake_transcript(monkeypatch, "urgent ... [inaudible]", low=True)
    call = await _received(db_session)
    await process(call.id)
    task = await _task(db_session, call)
    assert classifier.calls == 0
    assert task.priority == TaskPriority.URGENT
    assert "urgent keyword" in task.handover_context


async def test_low_quality_without_keypad_goes_to_human_review(
    db_session, storage, classifier, monkeypatch
):
    fake_transcript(monkeypatch, "mm hm", low=True)
    call = await _received(db_session)
    await process(call.id)
    task = await _task(db_session, call)
    assert task.category == TaskCategory.GENERAL_ADMINISTRATIVE
    assert task.priority == TaskPriority.HIGH  # HUMAN_REVIEW without an override


async def test_silent_voicemail_still_becomes_a_task(db_session, storage, classifier, monkeypatch):
    fake_transcript(monkeypatch, "", low=True)
    call = await _received(db_session)
    await process(call.id)
    await db_session.refresh(call)
    assert call.status == CallStatus.PROCESSED
    assert (await _task(db_session, call)) is not None


async def test_process_twice_is_a_no_op(db_session, storage, classifier, monkeypatch):
    fake_transcript(monkeypatch, "Hello.")
    call = await _received(db_session)
    await process(call.id)
    await process(call.id)
    tasks = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalars().all()
    assert len(tasks) == 1
    assert classifier.calls == 1


async def test_audit_details_hold_no_transcript_or_dob(
    db_session, storage, classifier, monkeypatch
):
    fake_transcript(monkeypatch, "My date of birth is the third of July.")
    call = await _received(db_session, keypad_dob=date(1985, 7, 3))
    await process(call.id)
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.case_id == call.case_id)))
        .scalars()
        .all()
    )
    blob = " ".join(str(e.details) for e in events)
    assert "1985" not in blob
    assert "third of July" not in blob
    assert "+61412345678" not in blob


async def test_failure_after_audio_is_recorded_and_not_retried(
    db_session, storage, classifier, monkeypatch
):
    def boom(data):
        raise RuntimeError("whisper crashed")

    monkeypatch.setattr(voicemail_service, "transcribe_audio_with_quality", boom)
    call = await _received(db_session)
    await process(call.id)
    await db_session.refresh(call)
    task = await _task(db_session, call)
    assert call.status == CallStatus.PROCESSED
    assert "RuntimeError" in (task.handover_context or "")
