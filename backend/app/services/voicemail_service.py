"""The voicemail channel (docs/superpowers/specs/2026-09-26-voicemail-channel-design.md).

A caller answers a keypad menu and leaves a message; staff get a callback
task. Nothing here ever sends anything to the caller.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from datetime import date, datetime
from functools import cache
from pathlib import PurePath
from uuid import UUID
from zoneinfo import ZoneInfo

import holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.llm import get_llm
from app.models.call import Call, CallKind, CallStatus
from app.models.case import IntakeCase, IntakeStatus
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User, UserRole
from app.services import booking_service, task_service, twilio_client
from app.services.audit_service import record_event
from app.services.call_service import _priority_for_gate
from app.services.content_classifier import classify_content
from app.services.system_actor import get_or_create_system_actor
from app.services.task_routing_gate import (
    TaskRoutingGateResult,
    TaskRoutingOutcome,
    evaluate_task_routing_gate,
)
from app.services.task_routing_rules import resolve_target_role
from app.services.transcription_service import TranscriptQuality, transcribe_audio_with_quality
from app.services.triage_service import is_urgent
from app.storage import object_storage

logger = logging.getLogger(__name__)

INTAKE_EMAIL = "voicemail-intake@system.vitalai.internal"
INTAKE_NAME = "Voicemail intake"

WITHHELD = "withheld"
# Twilio's older placeholders for a hidden caller ID. They are digit strings,
# so they would pass as real numbers; newer calls send words ("anonymous").
# ponytail: confirm against Twilio's docs when wiring the live number.
_LEGACY_WITHHELD = frozenset({"+266696687", "+7378742833", "+2562533", "+8656696", "+86282452253"})

INTENT_DIGITS = {"1": "appointment", "2": "results", "3": "prescription", "4": "other"}
_INTENT_CATEGORY = {
    "appointment": TaskCategory.APPOINTMENT_REQUEST,
    "results": TaskCategory.RESULTS_ENQUIRY,
    "prescription": TaskCategory.PRESCRIPTION_RENEWAL,
}
# What the caller pressed never overrides these: the words matter more.
_KEYPAD_NEVER_OVERRIDES = frozenset(
    {TaskCategory.URGENT_EMERGENCY, TaskCategory.COMPLAINT_ESCALATION}
)

AUDIO_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
}


@cache
def _holidays(region: str, year: int) -> holidays.HolidayBase:
    return holidays.country_holidays("AU", subdiv=region, years=year)


def clinic_is_open(now: datetime) -> bool:
    """Weekday, inside clinic hours, not a public holiday, all in clinic time."""
    local = now.astimezone(ZoneInfo(settings.clinic_timezone))
    closed_day = local.date() in _holidays(settings.clinic_holiday_region, local.year)
    if local.weekday() >= 5 or closed_day:
        return False
    return settings.clinic_open_hour <= local.hour < settings.clinic_close_hour


def is_withheld(from_number: str | None) -> bool:
    value = (from_number or "").strip()
    return value in _LEGACY_WITHHELD or not re.fullmatch(r"\+?\d{6,15}", value)


def parse_keypad_dob(digits: str | None, today: date | None = None) -> date | None:
    """DDMMYYYY from the keypad. Anything else is 'no DOB', never an error."""
    if not digits or not re.fullmatch(r"\d{8}", digits):
        return None
    try:
        dob = date(int(digits[4:]), int(digits[2:4]), int(digits[:2]))
    except ValueError:
        return None
    return dob if date(1900, 1, 1) <= dob <= (today or date.today()) else None


def audio_suffix(filename: str | None) -> str | None:
    suffix = PurePath(filename or "").suffix.lower()
    return suffix if suffix in AUDIO_TYPES else None


def audio_media_type(key: str) -> str:
    return AUDIO_TYPES.get(PurePath(key).suffix.lower(), "application/octet-stream")


async def intake_actor(db: AsyncSession) -> User:
    return await get_or_create_system_actor(db, INTAKE_EMAIL, INTAKE_NAME, UserRole.OPERATOR)


async def get_by_sid(db: AsyncSession, call_sid: str) -> Call | None:
    result = await db.execute(select(Call).where(Call.twilio_call_sid == call_sid))
    return result.scalar_one_or_none()


async def create_voicemail(
    db: AsyncSession,
    *,
    from_number: str | None,
    actor: User,
    call_sid: str | None = None,
    status: CallStatus = CallStatus.IN_PROGRESS,
    keypad_dob: date | None = None,
    keypad_intent: str | None = None,
    urgent_pressed: bool = False,
) -> Call:
    """A new case and Call row. Idempotent on call_sid (Twilio retries)."""
    if call_sid and (existing := await get_by_sid(db, call_sid)) is not None:
        return existing
    withheld = is_withheld(from_number)
    case = IntakeCase(
        contact_reason="Voicemail", contact_channel="voicemail", status=IntakeStatus.RECEIVED
    )
    db.add(case)
    await db.flush()
    call = Call(
        case_id=case.id,
        kind=CallKind.VOICEMAIL,
        phone_number=WITHHELD if withheld else (from_number or "").strip(),
        status=status,
        twilio_call_sid=call_sid,
        keypad_dob=keypad_dob,
        keypad_intent=keypad_intent,
        urgent_pressed=urgent_pressed,
    )
    db.add(call)
    await db.flush()
    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="voicemail.started",
        details={"call_id": str(call.id), "withheld": withheld},
    )
    await db.commit()
    await db.refresh(call)
    return call


async def store_audio(db: AsyncSession, call: Call, data: bytes, suffix: str) -> None:
    key = f"voicemail/{call.id}{suffix}"
    await asyncio.to_thread(object_storage.put_object, key, data, AUDIO_TYPES[suffix])
    call.audio_key = key
    await db.commit()


def urgent_script(call: Call, reasons: list[str]) -> str:
    who = (
        "The caller ID was withheld: listen for a callback number in the message."
        if call.phone_number == WITHHELD
        else f"Call {call.phone_number} back now."
    )
    return f"URGENT voicemail ({', '.join(reasons)}). {who}"


def _urgent_reasons(call: Call, category: TaskCategory, transcript: str) -> list[str]:
    reasons = []
    if call.urgent_pressed:
        reasons.append("caller pressed 9")
    if category == TaskCategory.URGENT_EMERGENCY:
        reasons.append("urgent category")
    if transcript and is_urgent(transcript):
        reasons.append("urgent keyword")
    return reasons


async def _task_for(db: AsyncSession, call: Call) -> Task:
    """Created before any slow step, so a failure lands on a Task that links
    to the call (and its audio) instead of a detached failure note."""
    result = await db.execute(select(Task).where(Task.call_id == call.id))
    task = result.scalars().first()
    if task is None:
        task = Task(
            case_id=call.case_id,
            call_id=call.id,
            source=TaskSource.CALL,
            category=TaskCategory.GENERAL_ADMINISTRATIVE,
            target_role=resolve_target_role(TaskCategory.GENERAL_ADMINISTRATIVE),
            priority=TaskPriority.HIGH,
            status=TaskItemStatus.PENDING,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
    return task


async def _categorise(
    db: AsyncSession, call: Call, low: bool, actor: User
) -> tuple[TaskCategory, float]:
    keypad = _INTENT_CATEGORY.get(call.keypad_intent or "")
    if low or not call.transcript:
        return (keypad, 1.0) if keypad else (TaskCategory.GENERAL_ADMINISTRATIVE, 0.0)
    category, confidence = await classify_content(
        db, get_llm(), call.transcript, actor=actor, channel="voicemail"
    )
    if keypad and category not in _KEYPAD_NEVER_OVERRIDES:
        return keypad, 1.0
    return category, confidence


async def _process(db: AsyncSession, call_id: UUID, actor: User) -> Task | None:
    call = await db.get(Call, call_id)
    if call is None or call.status != CallStatus.RECEIVED:
        return None
    task = await _task_for(db, call)

    if call.audio_key is None and call.twilio_recording_sid:
        data = await twilio_client.download_recording(call.twilio_recording_sid)
        await store_audio(db, call, data, ".wav")
        call.twilio_deleted = await twilio_client.delete_recording(call.twilio_recording_sid)
        await db.commit()

    audio = (
        await asyncio.to_thread(object_storage.get_object, call.audio_key)
        if call.audio_key
        else b""
    )
    transcript, quality = (
        await asyncio.to_thread(transcribe_audio_with_quality, audio)
        if audio
        else ("", TranscriptQuality.empty())
    )
    call.transcript = transcript
    call.transcript_quality = quality.as_dict()

    category, confidence = await _categorise(db, call, quality.low, actor)
    reasons = _urgent_reasons(call, category, transcript)
    gate = evaluate_task_routing_gate(category, confidence, transcript)
    if reasons:
        gate = TaskRoutingGateResult(
            outcome=TaskRoutingOutcome.HUMAN_REVIEW, override_reason="voicemail_urgent"
        )
    target_role = resolve_target_role(category)

    call.category = category
    call.confidence = confidence
    call.target_role = target_role
    call.status = CallStatus.PROCESSED
    task.category = category
    task.target_role = target_role
    task.priority = TaskPriority.URGENT if reasons else _priority_for_gate(gate)
    if reasons:
        task.handover_context = urgent_script(call, reasons)

    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="voicemail.received",
        details={
            "call_id": str(call.id),
            "task_id": str(task.id),
            "category": category.value,
            "outcome": gate.outcome.value,
            "urgent_reasons": reasons,
            "transcript_low_quality": quality.low,
            "keypad_fields": [
                name
                for name, value in (
                    ("dob", call.keypad_dob),
                    ("intent", call.keypad_intent),
                    ("urgent", call.urgent_pressed or None),
                )
                if value
            ],
        },
    )
    await db.commit()
    await db.refresh(task)
    return task


async def process(call_id: UUID) -> None:
    """Background entry point: its own session, never raises (nobody is left
    to raise to). Idempotent: only a `received` call is processed."""
    async with AsyncSessionLocal() as db:
        actor = await intake_actor(db)
        try:
            task = await _process(db, call_id, actor)
        except Exception as exc:
            logger.exception("Voicemail processing failed for call %s", call_id)
            await db.rollback()
            actor = await intake_actor(db)  # rollback expired the old instance
            call = await db.get(Call, call_id)
            if call is None:
                return
            if call.audio_key is None and call.twilio_recording_sid:
                # The audio never arrived (Twilio or the network): leave the
                # call `received` so the sweep retries the download.
                # ponytail: no retry cap; add one if a recording ever fails for good.
                return
            # Past this point the audio is ours, so a retry would fail the
            # same way: hand it to a human instead of looping.
            call.status = CallStatus.PROCESSED
            task = await _task_for(db, call)
            await task_service.record_agent_failure(
                db,
                task_id=task.id,
                case_id=call.case_id,
                actor=actor,
                stage="voicemail.process",
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
            await db.commit()
            return
    if task is not None and settings.agentic_pipeline_enabled:
        from app.agents import graph

        await graph.start_voicemail(task.id, call_id, urgent=task.priority == TaskPriority.URGENT)


_EXCERPT = 200


def callback_script(call: Call, state: Mapping) -> str:
    """The callback task's text. A template: no model decides what staff are
    told to offer."""
    lines = [
        "Caller ID withheld: listen for a callback number in the message."
        if call.phone_number == WITHHELD
        else f"Call back {call.phone_number}."
    ]
    if state.get("patient_name"):
        lines.append(
            f"Probable patient: {state['patient_name']} (caller ID and keypad date of birth match)."
        )
    else:
        lines.append("Caller not identified: confirm who called.")
    lines.append("Confirm the caller's full name and date of birth before discussing anything.")
    if state.get("intent"):
        lines.append(f"Reason: {state['intent'].replace('_', ' ')}.")
    excerpt = (call.transcript or "").strip()
    if excerpt:
        more = "..." if len(excerpt) > _EXCERPT else ""
        lines.append(f'They said: "{excerpt[:_EXCERPT]}{more}"')
    if (call.transcript_quality or {}).get("low"):
        lines.append("The transcript is unreliable: listen to the recording.")
    if state.get("proposed_slots"):
        slots = ", ".join(
            booking_service.format_slot(datetime.fromisoformat(s)) for s in state["proposed_slots"]
        )
        lines.append(f"Offer {booking_service.titled(state['booking_doctor_name'])}: {slots}.")
    elif state.get("dispatch_result") == "booking_hold":
        lines.append("No appointment time could be proposed: book by hand.")
    return "\n".join(lines)


async def handle_call_ended(db: AsyncSession, call: Call, actor: User) -> Task | None:
    """The call ended with no recording coming (spec §4 step 5). Pressed 9
    first: an URGENT callback task. Otherwise nothing to act on."""
    if call.status not in (CallStatus.IN_PROGRESS, CallStatus.RECORDING):
        return None
    call.status = CallStatus.ABANDONED
    task = None
    if call.urgent_pressed:
        task = Task(
            case_id=call.case_id,
            call_id=call.id,
            source=TaskSource.CALL,
            category=TaskCategory.GENERAL_ADMINISTRATIVE,
            target_role=resolve_target_role(TaskCategory.GENERAL_ADMINISTRATIVE),
            priority=TaskPriority.URGENT,
            status=TaskItemStatus.PENDING,
            handover_context=urgent_script(
                call, ["caller pressed 9 and hung up before leaving a message"]
            ),
        )
        db.add(task)
    else:
        case = await db.get(IntakeCase, call.case_id)
        if case is not None:
            case.status = IntakeStatus.INCOMPLETE
    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="voicemail.abandoned",
        details={"call_id": str(call.id), "urgent": call.urgent_pressed},
    )
    await db.commit()
    return task
