from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.permissions import MANAGE_CASES, VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.call import (
    CallCreate,
    CallEscalateRequest,
    CallEscalationOut,
    CallOut,
    CallRouteOut,
    CallRouteRequest,
    CallRoutingOverride,
)
from app.services import call_service
from app.services.triage_service import ConsentGatingError

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_call_endpoint(
    payload: CallCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
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
        call, triage, decision = await call_service.route_call(db, call_id, payload, actor)
    except call_service.CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (call_service.TranscriptRequiredError, ConsentGatingError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CallRouteOut(
        call=call,
        category=triage.category,
        confidence=triage.confidence,
        rationale=triage.rationale,
        routing_action=decision.action,
        target_queue=decision.target_queue,
        escalated=decision.escalated,
    )


@router.post("/{call_id}/override-routing", response_model=CallRouteOut)
async def override_call_routing_endpoint(
    call_id: UUID,
    payload: CallRoutingOverride,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        call, triage, decision = await call_service.override_call_routing(
            db, call_id, payload, actor
        )
    except call_service.CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except call_service.TranscriptRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CallRouteOut(
        call=call,
        category=triage.category,
        confidence=triage.confidence,
        rationale=triage.rationale,
        routing_action=decision.action,
        target_queue=decision.target_queue,
        escalated=decision.escalated,
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
        call=call,
        task_id=task.id,
        task_priority=task.priority,
        target_queue=task.target_queue or "",
        handover_context=context,
    )


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
