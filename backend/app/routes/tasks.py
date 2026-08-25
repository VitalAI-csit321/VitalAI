from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission, require_permission
from app.auth.permissions import DELETE_MESSAGES, MANAGE_CASES, VIEW_CLINICAL, VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.task import (
    TaskCommentCreate,
    TaskCommentOut,
    TaskCreate,
    TaskEscalateRequest,
    TaskOut,
    TaskOverrideRequest,
    TaskUpdate,
)
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


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task_endpoint(
    task_id: UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        return await task_service.update_task(db, task_id, payload, actor)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except task_service.AssigneeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{task_id}/comments", response_model=list[TaskCommentOut])
async def list_comments_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    return await task_service.list_comments(db, task_id)


@router.post(
    "/{task_id}/comments", response_model=TaskCommentOut, status_code=status.HTTP_201_CREATED
)
async def add_comment_endpoint(
    task_id: UUID,
    payload: TaskCommentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_QUEUE)),
):
    try:
        return await task_service.add_comment(db, task_id, payload, actor)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{task_id}/override", response_model=TaskOut)
async def override_task_endpoint(
    task_id: UUID,
    payload: TaskOverrideRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE_CASES)),
):
    try:
        return await task_service.override_task(
            db, task_id, payload.category, payload.reason, actor
        )
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{task_id}/escalate", response_model=TaskOut)
async def escalate_task_endpoint(
    task_id: UUID,
    payload: TaskEscalateRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await task_service.escalate_task(db, task_id, payload.reason, actor)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except task_service.TaskForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except task_service.TaskAlreadyEscalatedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/archive", response_model=TaskOut)
async def archive_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await task_service.archive_task(db, task_id, actor)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except task_service.TaskForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete("/{task_id}", response_model=TaskOut)
async def delete_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(DELETE_MESSAGES)),
):
    try:
        return await task_service.soft_delete_task(db, task_id, actor)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except task_service.TaskForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/{task_id}/read", response_model=TaskOut)
async def mark_task_read_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    try:
        return await task_service.mark_task_read(db, task_id, actor)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except task_service.TaskForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
