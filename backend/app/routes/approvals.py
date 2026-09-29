from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import APPROVE_ACTION
from app.config import settings
from app.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.user import User
from app.schemas.approval import (
    ApprovalApproveBody,
    ApprovalListResponse,
    ApprovalRejectBody,
    ApprovalRequestOut,
)
from app.services import approval_service, assignment_service, email_service, outlook_sync_service
from app.services.approval_service import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from app.services.assignment_service import (
    AssignmentExistsError,
    DoctorNotFoundError,
    NotADoctorError,
    PatientNotFoundError,
)
from app.services.email_service import EmailSendError
from app.services.outlook_auth import OutlookAuthRequiredError

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def _execute_patient_assignment_suggested(
    db: AsyncSession, request: ApprovalRequest, actor: User
) -> None:
    payload = request.resolved_payload or request.payload
    await assignment_service.assign_patient(
        db,
        doctor_id=UUID(payload["suggested_doctor_id"]),
        patient_id=UUID(payload["patient_id"]),
        actor=actor,
    )


async def _execute_email_draft_reply(
    db: AsyncSession, request: ApprovalRequest, actor: User
) -> None:
    """Send an approved draft reply, exactly what the human approved."""
    payload = request.resolved_payload or request.payload
    await email_service.deliver_reply(
        db,
        email_id=payload.get("email_id"),
        task_id=payload.get("task_id"),
        draft=payload.get("draft"),
        actor=actor,
        case_id=request.case_id,
        approval_id=request.id,
    )


def _schedule_agent_resume(
    background_tasks: BackgroundTasks | None, request: ApprovalRequest, decision: dict
) -> None:
    """Hand a decision back to the paused agent thread, if this row has one.

    external_ref is the graph's thread_id and is written only by the agent's
    create_approval node, so every pre-existing approval path skips this.

    Pass background_tasks=None when the handler is about to raise: FastAPI
    never runs a response's BackgroundTasks once an HTTPException replaces
    that response, so the resume goes through the poller's strong-ref
    scheduler instead.
    """
    if not settings.agentic_pipeline_enabled or not request.external_ref:
        return
    # Imported here so the flag-off app never loads langgraph or psycopg.
    from app.agents import graph as agent_graph

    if background_tasks is None:
        outlook_sync_service.schedule(agent_graph.resume, request.external_ref, decision)
    else:
        background_tasks.add_task(agent_graph.resume, request.external_ref, decision)


_ACTION_EXECUTORS = {
    "patient.assignment.suggested": _execute_patient_assignment_suggested,
    "email.draft_reply": _execute_email_draft_reply,
}


@router.get("", response_model=ApprovalListResponse)
async def list_approvals_endpoint(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    action_type: str | None = None,
    case_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(APPROVE_ACTION)),
):
    items, total = await approval_service.list_approvals(
        db,
        status=status_filter,
        action_type=action_type,
        case_id=case_id,
        limit=limit,
        offset=offset,
    )
    return ApprovalListResponse(
        items=[ApprovalRequestOut.model_validate(i) for i in items], total=total
    )


@router.post("/{approval_id}/approve", response_model=ApprovalRequestOut)
async def approve_endpoint(
    approval_id: UUID,
    payload: ApprovalApproveBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    try:
        approved = await approval_service.approve(
            db,
            approval_id,
            actor,
            resolved_payload=payload.resolved_payload,
            notes=payload.notes,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApprovalAlreadyDecidedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    executor = _ACTION_EXECUTORS.get(approved.action_type)
    if executor is not None:
        try:
            await executor(db, approved, actor)
        except (DoctorNotFoundError, PatientNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except NotADoctorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
        except AssignmentExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except (EmailSendError, OutlookAuthRequiredError) as exc:
            # The approval decision itself succeeded and is recorded; what
            # failed is delivery. draft_sent stays False. An agent thread still
            # has to be resumed, as undelivered, or it sits paused forever:
            # the row is APPROVED now, so approving again returns 409.
            _schedule_agent_resume(
                None,
                approved,
                {
                    "approved": True,
                    "delivered": False,
                    "error": str(exc),
                    "draft": (approved.resolved_payload or approved.payload).get("draft"),
                },
            )
            # ponytail: no retry endpoint for this. Re-approving is refused
            # (409), so the reply is sent by hand; the task's handover_context
            # says so on the agent path. Add a retry path only if this turns
            # out to be a recurring failure in practice, not preemptively.
            if isinstance(exc, EmailSendError):
                # 502: the upstream mail provider refused it.
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
                ) from exc
            # 503, distinct from a send failure: nobody is signed in, which
            # needs a human to re-run scripts/outlook_login.py, not a retry.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

    draft = (approved.resolved_payload or approved.payload).get("draft")
    _schedule_agent_resume(background_tasks, approved, {"approved": True, "draft": draft})
    return approved


@router.post("/{approval_id}/reject", response_model=ApprovalRequestOut)
async def reject_endpoint(
    approval_id: UUID,
    payload: ApprovalRejectBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    try:
        rejected = await approval_service.reject(db, approval_id, actor, notes=payload.notes)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApprovalAlreadyDecidedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # A rejection must resume too, or the thread stays paused forever.
    _schedule_agent_resume(background_tasks, rejected, {"approved": False})
    return rejected
