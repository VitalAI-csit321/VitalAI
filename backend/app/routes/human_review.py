from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission
from app.auth.permissions import VIEW_CLINICAL, VIEW_QUEUE
from app.database import get_db
from app.models.human_review import TaskStatus, TaskType
from app.models.user import User
from app.schemas.human_review import (
    HumanReviewCompleteBody,
    HumanReviewTaskCreate,
    HumanReviewTaskListResponse,
    HumanReviewTaskOut,
    WorkflowDailyCount,
)
from app.services import human_review_service
from app.services.human_review_service import (
    HumanReviewTaskNotFoundError,
    HumanReviewTaskWrongRoleError,
    HumanReviewTaskWrongStateError,
)

router = APIRouter(prefix="/human-review", tags=["human-review"])


@router.get("", response_model=HumanReviewTaskListResponse)
async def list_tasks_endpoint(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    task_type: TaskType | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    items, total = await human_review_service.list_tasks(
        db,
        actor,
        status=status_filter,
        task_type=task_type,
        limit=limit,
        offset=offset,
    )
    return HumanReviewTaskListResponse(
        items=[HumanReviewTaskOut.model_validate(i) for i in items], total=total
    )


_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@router.get("/stats/daily", response_model=list[WorkflowDailyCount])
async def get_workflow_daily_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())
    counts = await human_review_service.count_tasks_by_day(db, actor, week_start)
    return [
        WorkflowDailyCount(
            day=_DAY_LABELS[offset],
            value=counts.get((week_start + timedelta(days=offset)).date(), 0),
        )
        for offset in range(7)
    ]


@router.post("", response_model=HumanReviewTaskOut, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    payload: HumanReviewTaskCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    return await human_review_service.create_task(
        db,
        actor,
        task_type=payload.task_type,
        contact_reason=payload.contact_reason,
        priority=payload.priority,
        assigned_to=payload.assigned_to,
        reviewed=payload.reviewed,
        notes=payload.notes,
    )


@router.post("/{task_id}/claim", response_model=HumanReviewTaskOut)
async def claim_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await human_review_service.claim_task(db, task_id, actor)
    except HumanReviewTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HumanReviewTaskWrongRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HumanReviewTaskWrongStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/complete", response_model=HumanReviewTaskOut)
async def complete_task_endpoint(
    task_id: UUID,
    payload: HumanReviewCompleteBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await human_review_service.complete_task(db, task_id, actor, notes=payload.notes)
    except HumanReviewTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HumanReviewTaskWrongRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HumanReviewTaskWrongStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/reject", response_model=HumanReviewTaskOut)
async def reject_task_endpoint(
    task_id: UUID,
    payload: HumanReviewCompleteBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await human_review_service.reject_task(db, task_id, actor, notes=payload.notes)
    except HumanReviewTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HumanReviewTaskWrongRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HumanReviewTaskWrongStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/escalate", response_model=HumanReviewTaskOut)
async def escalate_task_endpoint(
    task_id: UUID,
    payload: HumanReviewCompleteBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await human_review_service.escalate_task(db, task_id, actor, notes=payload.notes)
    except HumanReviewTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HumanReviewTaskWrongRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HumanReviewTaskWrongStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
