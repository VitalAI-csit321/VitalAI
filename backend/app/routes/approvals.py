from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import APPROVE_ACTION
from app.config import settings
from app.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.email import Email
from app.models.task import Task
from app.models.user import User
from app.schemas.approval import (
    ApprovalApproveBody,
    ApprovalListResponse,
    ApprovalRejectBody,
    ApprovalRequestOut,
)
from app.services import approval_service, assignment_service, outlook_auth, outlook_client
from app.services.approval_service import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from app.services.assignment_service import (
    AssignmentExistsError,
    DoctorNotFoundError,
    NotADoctorError,
    PatientNotFoundError,
)
from app.services.audit_service import record_event
from app.services.outlook_auth import OutlookAuthRequiredError

router = APIRouter(prefix="/approvals", tags=["approvals"])


class EmailSendError(Exception):
    """Outlook refused an approved reply. The approval stays decided, but the
    task is deliberately left draft_sent=False so the failure is visible rather
    than recorded as a delivered message."""


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
    """Send an approved draft reply.

    With the Outlook connector disabled this stays what it always was: "sent"
    is DB-level state, no message leaves the system. With it enabled the draft
    is delivered through Graph first, and only a successful send sets
    draft_sent, so a delivery failure can never be recorded as a sent reply.
    """
    payload = request.resolved_payload or request.payload
    draft = payload.get("draft")
    email_id = payload.get("email_id")
    delivered = False

    if settings.outlook_enabled and email_id is not None and draft:
        email = await db.get(Email, UUID(email_id))
        if email is not None and email.external_id:
            token = await outlook_auth.get_access_token()
            try:
                await outlook_client.send_reply(token, email.external_id, draft)
            except httpx.HTTPError as exc:
                raise EmailSendError(
                    f"Outlook rejected the reply to message {email.external_id}: {exc}"
                ) from exc
            delivered = True

    task_id = payload.get("task_id")
    if task_id is not None:
        task = await db.get(Task, UUID(task_id))
        if task is not None:
            task.draft_sent = True
            if draft is not None:
                task.draft_text = draft
    await record_event(
        db,
        actor=actor,
        case_id=request.case_id,
        action="email.sent",
        details={
            "email_id": email_id,
            "approval_id": str(request.id),
            # Distinguishes a real Graph delivery from the simulated path, so
            # the audit log does not claim more than actually happened.
            "delivered": delivered,
        },
    )
    await db.commit()


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
        except EmailSendError as exc:
            # 502: the approval decision itself succeeded and is recorded; what
            # failed is the upstream mail provider. draft_sent stays False.
            # ponytail: no retry endpoint for this. The operator re-approves or
            # the reply is sent by hand. Add a retry path only if this turns out
            # to be a recurring failure in practice, not preemptively.
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        except OutlookAuthRequiredError as exc:
            # Distinct from a send failure: nobody is signed in, which needs a
            # human to re-run scripts/outlook_login.py, not a retry.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

    return approved


@router.post("/{approval_id}/reject", response_model=ApprovalRequestOut)
async def reject_endpoint(
    approval_id: UUID,
    payload: ApprovalRejectBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    try:
        return await approval_service.reject(db, approval_id, actor, notes=payload.notes)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApprovalAlreadyDecidedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
