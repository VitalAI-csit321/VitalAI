from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import MANAGE_CASES, VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.call import (
    CallCreate,
    CallEscalateRequest,
    CallEscalationOut,
    CallOut,
    CallOverrideOut,
    CallRouteOut,
    CallRouteRequest,
    CallRoutingOverride,
    CallTranscribeOut,
)
from app.services import call_service
from app.services.transcription_service import EmptyTranscriptError, transcribe_audio
from app.services.triage_service import ConsentGatingError

router = APIRouter(prefix="/calls", tags=["calls"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # generous for a few minutes of voice audio


@router.post("", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_call_endpoint(
    payload: CallCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_QUEUE)),
):
    try:
        return await call_service.create_call(db, payload, actor)
    except call_service.CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[CallOut])
async def list_calls_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    return await call_service.list_calls(db)


@router.post("/{call_id}/route", response_model=CallRouteOut)
async def route_call_endpoint(
    call_id: UUID,
    payload: CallRouteRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        call, task, gate = await call_service.route_call(db, call_id, payload, actor)
    except call_service.CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (call_service.TranscriptRequiredError, ConsentGatingError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # route_call() always sets these before returning.
    assert call.category is not None
    assert call.confidence is not None
    assert call.target_role is not None
    return CallRouteOut(
        call=CallOut.model_validate(call),
        task_id=task.id,
        category=call.category,
        confidence=call.confidence,
        target_role=call.target_role,
        outcome=gate.outcome,
        override_reason=gate.override_reason,
    )


@router.post("/{call_id}/override-routing", response_model=CallOverrideOut)
async def override_call_routing_endpoint(
    call_id: UUID,
    payload: CallRoutingOverride,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        call, task = await call_service.override_call_routing(db, call_id, payload, actor)
    except call_service.CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except call_service.TranscriptRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except call_service.CallNotRoutedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # override_call_routing() always sets these before returning.
    assert call.category is not None
    assert call.target_role is not None
    return CallOverrideOut(
        call=CallOut.model_validate(call),
        task_id=task.id,
        category=call.category,
        target_role=call.target_role,
    )


@router.post("/{call_id}/escalate", response_model=CallEscalationOut)
async def escalate_call_endpoint(
    call_id: UUID,
    payload: CallEscalateRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        call, task, context = await call_service.escalate_call(db, call_id, payload, actor)
    except (call_service.CallNotFoundError, call_service.AssigneeNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        call_service.TranscriptRequiredError,
        call_service.CallNotRoutedError,
        call_service.DuplicateEscalationError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CallEscalationOut(
        call=CallOut.model_validate(call),
        task_id=task.id,
        task_priority=task.priority,
        handover_context=context,
    )


@router.post("/transcribe", response_model=CallTranscribeOut)
async def transcribe_call_endpoint(
    audio: UploadFile = File(...),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    raw = await audio.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No audio uploaded"
        )
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio file too large"
        )
    try:
        transcript = transcribe_audio(raw)
    except EmptyTranscriptError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return CallTranscribeOut(transcript=transcript)


@router.get("/{call_id}", response_model=CallOut)
async def get_call_endpoint(
    call_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    call = await call_service.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call
