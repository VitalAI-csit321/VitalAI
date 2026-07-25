from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import APPROVE_ACTION
from app.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.user import User
from app.schemas.approval import (
    ApprovalApproveBody,
    ApprovalListResponse,
    ApprovalRejectBody,
    ApprovalRequestOut,
)
from app.services import approval_service, assignment_service
from app.services.approval_service import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from app.services.assignment_service import (
    AssignmentExistsError,
    DoctorNotFoundError,
    NotADoctorError,
    PatientNotFoundError,
)

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


_ACTION_EXECUTORS = {
    "patient.assignment.suggested": _execute_patient_assignment_suggested,
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
