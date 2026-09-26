"""The fake voicemail intake (voicemail spec §6): the same fields a Twilio call
ends with, from an uploaded file. Kept permanently as the demo and test path."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import MANAGE_CASES
from app.database import get_db
from app.models.call import CallStatus
from app.models.user import User
from app.routes.calls import MAX_AUDIO_BYTES
from app.schemas.call import VoicemailSimulateOut
from app.services import voicemail_service

router = APIRouter(prefix="/voicemails", tags=["voicemails"])


@router.post("/simulate", response_model=VoicemailSimulateOut, status_code=status.HTTP_202_ACCEPTED)
async def simulate_voicemail_endpoint(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    from_number: str = Form(..., max_length=20),
    dob_digits: str | None = Form(None),
    intent_digit: str | None = Form(None),
    urgent: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    suffix = voicemail_service.audio_suffix(audio.filename)
    if suffix is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported audio type"
        )
    raw = await audio.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No audio uploaded"
        )
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio file too large"
        )
    call = await voicemail_service.create_voicemail(
        db,
        from_number=from_number,
        actor=actor,
        status=CallStatus.RECEIVED,
        keypad_dob=voicemail_service.parse_keypad_dob(dob_digits),
        keypad_intent=voicemail_service.INTENT_DIGITS.get(intent_digit or ""),
        urgent_pressed=urgent,
    )
    await voicemail_service.store_audio(db, call, raw, suffix)
    # Transcription and a model call: minutes on CPU, so after the response.
    background_tasks.add_task(voicemail_service.process, call.id)
    return VoicemailSimulateOut(call_id=call.id, case_id=call.case_id)
