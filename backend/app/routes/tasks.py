from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.permissions import APPROVE_ACTION, VIEW_QUEUE
from app.database import get_db
from app.models.task import TaskItemStatus, TaskPriority
from app.models.user import User
from app.schemas.task import TaskBoardOut, TaskColumnCounts, TaskCreate, TaskOut, TaskUpdate
from app.services import task_service
from app.services.task_service import TaskNotFoundError, TaskStateError

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/board", response_model=TaskBoardOut)
async def get_task_board(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    """Kanban board grouped by status — backs the Escalations page."""
    columns_raw = await task_service.list_tasks_by_column(db)
    counts_raw = await task_service.column_counts(db)
    return TaskBoardOut(
        columns={k: [TaskOut.model_validate(t) for t in v] for k, v in columns_raw.items()},
        counts=TaskColumnCounts(
            pending=counts_raw.get("pending", 0),
            in_progress=counts_raw.get("in_progress", 0),
            escalated=counts_raw.get("escalated", 0),
            completed=counts_raw.get("completed", 0),
        ),
    )


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    return await task_service.create_task(db, payload, actor)


@router.get("", response_model=list[TaskOut])
async def list_tasks_endpoint(
    task_status: list[TaskItemStatus] | None = Query(default=None, alias="status"),
    priority: list[TaskPriority] | None = Query(default=None),
    assigned_to: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    items, _ = await task_service.list_tasks(
        db, status=task_status, priority=priority, assigned_to=assigned_to,
        limit=limit, offset=offset,
    )
    return [TaskOut.model_validate(t) for t in items]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    task = await task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task_endpoint(
    task_id: UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    try:
        return await task_service.update_task(db, task_id, payload, actor)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
