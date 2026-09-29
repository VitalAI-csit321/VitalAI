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
_VOICE = "Polly.Nicole"

CLOSED = (
    "Hi, thanks for calling Green Care Family Medical Clinic. "
    "We're closed right now, but we're open 8am to 6pm, "
    "Monday to Friday, and we'd love to help then. "
    "If this is an emergency, please hang up and dial triple zero. Take care."
)
NOTICE = (
    "Hi, thanks for calling Green Care Family Medical Clinic. "
    "If this is an emergency, please hang up and dial triple zero. "
    "Just so you know, this call is recorded so our team can get back to you."
)
URGENT_PROMPT = "If your call is urgent, press 9. Otherwise, just stay on the line."
DOB_PROMPT = (
    "Please enter the patient's date of birth, as day, month and year. "
    "For example, 0 3 0 7 1 9 8 5. Then press hash."
)
INTENT_PROMPT = (
    "For appointments, press 1. For test results, press 2. "
    "For prescriptions, press 3. For anything else, press 4."
)
# Caller ID is the callback number, so only a withheld caller is asked for one:
# spoken digits are the least reliable part of a transcript.
RECORD_PROMPT = (
    "After the tone, please tell us the patient's full name and how we can help. "
    "Press hash when you're finished."
)
RECORD_PROMPT_WITHHELD = (
    "After the tone, please tell us the patient's full name, the best number to call you "
    "back on, and how we can help. Press hash when you're finished."
)
THANKS = (
    "Thanks so much. We've got your message, and someone from our team "
    "will call you back soon. Goodbye!"
)
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
    gather.say(prompt, language=_LANG, voice=_VOICE)
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
        vr.say(CLOSED, language=_LANG, voice=_VOICE)
        vr.hangup()
        return _twiml(vr)
    await voicemail_service.create_voicemail(
        db, from_number=form.get("From"), actor=actor, call_sid=form["CallSid"]
    )
    vr.say(NOTICE, language=_LANG, voice=_VOICE)
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
        prompt = (
            RECORD_PROMPT_WITHHELD
            if call.phone_number == voicemail_service.WITHHELD
            else RECORD_PROMPT
        )
        vr.say(prompt, language=_LANG, voice=_VOICE)
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
    vr.say(THANKS, language=_LANG, voice=_VOICE)
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
