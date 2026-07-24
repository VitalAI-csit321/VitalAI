from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import MANAGE_CASES, VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.task import TaskCreate, TaskOut
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        return await task_service.create_task(db, payload, actor)
    except (task_service.CaseNotFoundError, task_service.AssigneeNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[TaskOut])
async def list_tasks_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    return await task_service.list_tasks(db)


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
