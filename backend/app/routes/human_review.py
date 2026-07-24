from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import VIEW_QUEUE
from app.database import get_db
from app.models.human_review import TaskStatus, TaskType
from app.models.user import User
from app.schemas.human_review import (
    HumanReviewCompleteBody,
    HumanReviewTaskListResponse,
    HumanReviewTaskOut,
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
    actor: User = Depends(require_permission(VIEW_QUEUE)),
):
    items, total = await human_review_service.list_tasks(
        db,
        target_role=actor.role,
        status=status_filter,
        task_type=task_type,
        limit=limit,
        offset=offset,
    )
    return HumanReviewTaskListResponse(
        items=[HumanReviewTaskOut.model_validate(i) for i in items], total=total
    )


@router.post("/{task_id}/claim", response_model=HumanReviewTaskOut)
async def claim_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_QUEUE)),
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
    actor: User = Depends(require_permission(VIEW_QUEUE)),
):
    try:
        return await human_review_service.complete_task(db, task_id, actor, notes=payload.notes)
    except HumanReviewTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HumanReviewTaskWrongRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HumanReviewTaskWrongStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
