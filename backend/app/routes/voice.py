"""Twilio voicemail webhooks (voicemail spec §4). Mounted only when
twilio_enabled. Every handler is cheap DB work and TwiML: Twilio waits about
15 seconds before the caller hears an application error. Call state lives on
the Call row keyed by CallSid, never in URLs, so no DOB reaches a log."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import Gather, VoiceResponse

from app.config import settings
from app.database import get_db
from app.models.call import CallStatus
from app.services import twilio_client, voicemail_service
from app.services.audit_service import record_event

router = APIRouter(prefix="/voice", tags=["voice"])

_ROUTE_ROOT = "/api/v1/voice"
_LANG = "en-AU"

CLOSED = (
    "The clinic is closed. Please call back between 8am and 6pm, Monday to Friday. "
    "If this is an emergency, hang up and dial triple zero."
)
NOTICE = (
    "If this is an emergency, hang up and dial triple zero. "
    "This call is recorded so our staff can respond to your message."
)
URGENT_PROMPT = "If this is urgent, press 9. Otherwise press any other key or wait."
DOB_PROMPT = (
    "Enter the patient's date of birth as day, month, year, "
    "for example 0 3 0 7 1 9 8 5, then press hash."
)
INTENT_PROMPT = "Press 1 for appointments, 2 for results, 3 for prescriptions, 4 for anything else."
RECORD_PROMPT = (
    "After the tone, say the patient's full name, a number we can call you back on, "
    "and your message. Press hash when you're done."
)
THANKS = "Thank you. We'll call you back."
_ENDED = {"completed", "busy", "no-answer", "failed", "canceled"}


def _url(path: str) -> str:
    return f"{settings.twilio_webhook_base_url.rstrip('/')}{_ROUTE_ROOT}{path}"


def _twiml(vr: VoiceResponse) -> Response:
    return Response(content=str(vr), media_type="application/xml")


def _gather(
    vr: VoiceResponse, step: str, prompt: str, *, num_digits: int, finish_on_key: str | None = None
) -> None:
    kwargs = {
        "action": _url(f"/gather/{step}"),
        "method": "POST",
        "num_digits": num_digits,
        "timeout": 6,
        # Without this Twilio moves on silently when nothing is pressed and
        # never calls the action URL.
        "action_on_empty_result": True,
    }
    if finish_on_key:
        kwargs["finish_on_key"] = finish_on_key
    gather = Gather(**kwargs)
    gather.say(prompt, language=_LANG)
    vr.append(gather)


async def twilio_form(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    form = {key: str(value) for key, value in (await request.form()).items()}
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    signature = request.headers.get("X-Twilio-Signature", "")
    if (
        not twilio_client.valid_signature(path, form, signature)
        or form.get("AccountSid") != settings.twilio_account_sid
    ):
        actor = await voicemail_service.intake_actor(db)
        await record_event(
            db, actor=actor, action="voicemail.rejected_request", details={"path": request.url.path}
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio request")
    return form


@router.post("/incoming")
async def incoming(form: dict = Depends(twilio_form), db: AsyncSession = Depends(get_db)):
    vr = VoiceResponse()
    actor = await voicemail_service.intake_actor(db)
    if not voicemail_service.clinic_is_open(datetime.now(UTC)):
        await record_event(db, actor=actor, action="voicemail.after_hours_call", details={})
        await db.commit()
        vr.say(CLOSED, language=_LANG)
        vr.hangup()
        return _twiml(vr)
    await voicemail_service.create_voicemail(
        db, from_number=form.get("From"), actor=actor, call_sid=form["CallSid"]
    )
    vr.say(NOTICE, language=_LANG)
    _gather(vr, "urgent", URGENT_PROMPT, num_digits=1)
    return _twiml(vr)


@router.post("/gather/{step}")
async def gather(
    step: Literal["urgent", "dob", "intent"],
    form: dict = Depends(twilio_form),
    db: AsyncSession = Depends(get_db),
):
    vr = VoiceResponse()
    call = await voicemail_service.get_by_sid(db, form["CallSid"])
    if call is None:
        vr.hangup()
        return _twiml(vr)
    digits = form.get("Digits", "")
    if step == "urgent":
        call.urgent_pressed = digits == "9"
        _gather(vr, "dob", DOB_PROMPT, num_digits=8, finish_on_key="#")
    elif step == "dob":
        call.keypad_dob = voicemail_service.parse_keypad_dob(digits)
        _gather(vr, "intent", INTENT_PROMPT, num_digits=1)
    else:
        call.keypad_intent = voicemail_service.INTENT_DIGITS.get(digits)
        call.status = CallStatus.RECORDING
        vr.say(RECORD_PROMPT, language=_LANG)
        vr.record(
            action=_url("/done"),
            method="POST",
            max_length=120,
            timeout=10,  # Twilio's default of 5 s of silence cuts off callers who pause
            play_beep=True,
            finish_on_key="#",
            recording_status_callback=_url("/recording"),
            recording_status_callback_method="POST",
            recording_status_callback_event="completed absent",
        )
    await db.commit()
    return _twiml(vr)


@router.post("/done")
async def done(form: dict = Depends(twilio_form)):
    vr = VoiceResponse()
    vr.say(THANKS, language=_LANG)
    vr.hangup()
    return _twiml(vr)


@router.post("/recording", status_code=status.HTTP_204_NO_CONTENT)
async def recording(
    background_tasks: BackgroundTasks,
    form: dict = Depends(twilio_form),
    db: AsyncSession = Depends(get_db),
):
    call = await voicemail_service.get_by_sid(db, form["CallSid"])
    if call is None or call.status not in (CallStatus.IN_PROGRESS, CallStatus.RECORDING):
        return Response(status_code=status.HTTP_204_NO_CONTENT)  # duplicate or replay
    if form.get("RecordingStatus") == "completed" and form.get("RecordingSid"):
        call.twilio_recording_sid = form["RecordingSid"]
        call.status = CallStatus.RECEIVED
        await db.commit()
        background_tasks.add_task(voicemail_service.process, call.id)
    elif form.get("RecordingStatus") == "absent":
        actor = await voicemail_service.intake_actor(db)
        await voicemail_service.handle_call_ended(db, call, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/status", status_code=status.HTTP_204_NO_CONTENT)
async def call_status(form: dict = Depends(twilio_form), db: AsyncSession = Depends(get_db)):
    call = await voicemail_service.get_by_sid(db, form["CallSid"])
    # Only a call still in the menu. `recording` waits for the recording
    # callback, which Twilio can send after this one.
    if form.get("CallStatus") in _ENDED and call is not None:
        if call.status == CallStatus.IN_PROGRESS:
            actor = await voicemail_service.intake_actor(db)
            await voicemail_service.handle_call_ended(db, call, actor)
        elif call.status == CallStatus.RECORDING and call.urgent_pressed:
            # A hang-up during the record prompt sends no recording callback
            # at all. Raise the urgent task now; a recording that does arrive
            # later is processed onto this same task.
            await voicemail_service.ensure_task(db, call)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
