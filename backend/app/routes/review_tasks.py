"""Human-in-the-loop review task routes — backs the Review Queue page."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.permissions import APPROVE_ACTION, VIEW_QUEUE
from app.database import get_db
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.user import User
from app.services.audit_service import record_event

router = APIRouter(prefix="/review-tasks", tags=["review-tasks"])


from pydantic import BaseModel
from datetime import datetime


class ReviewTaskOut(BaseModel):
    id: UUID
    case_id: UUID
    task_type: str
    status: str
    assigned_to: UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewTaskCreate(BaseModel):
    case_id: UUID
    task_type: TaskType = TaskType.TRIAGE_REVIEW
    notes: str | None = None


class ReviewTaskUpdate(BaseModel):
    status: TaskStatus | None = None
    assigned_to: UUID | None = None
    notes: str | None = None


class ReviewTaskListResponse(BaseModel):
    items: list[ReviewTaskOut]
    total: int


class ReviewTaskSummary(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    cancelled: int


@router.get("", response_model=ReviewTaskListResponse)
async def list_review_tasks(
    task_status: str | None = Query(default=None, alias="status"),
    task_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    stmt = select(HumanReviewTask)
    count_stmt = select(func.count()).select_from(HumanReviewTask)

    if task_status:
        try:
            s = TaskStatus(task_status)
            stmt = stmt.where(HumanReviewTask.status == s)
            count_stmt = count_stmt.where(HumanReviewTask.status == s)
        except ValueError:
            pass

    if task_type:
        try:
            t = TaskType(task_type)
            stmt = stmt.where(HumanReviewTask.task_type == t)
            count_stmt = count_stmt.where(HumanReviewTask.task_type == t)
        except ValueError:
            pass

    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        stmt.order_by(HumanReviewTask.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(result.scalars().all())
    return ReviewTaskListResponse(items=[ReviewTaskOut.model_validate(t) for t in items], total=total)


@router.post("", response_model=ReviewTaskOut, status_code=status.HTTP_201_CREATED)
async def create_review_task(
    payload: ReviewTaskCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    task = HumanReviewTask(
        case_id=payload.case_id,
        task_type=payload.task_type,
        status=TaskStatus.PENDING,
        notes=payload.notes,
    )
    db.add(task)
    await db.flush()
    await record_event(db, actor=actor, action="review_task.created",
                       details={"task_id": str(task.id), "case_id": str(payload.case_id)})
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/summary", response_model=ReviewTaskSummary)
async def review_task_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    result = await db.execute(
        select(HumanReviewTask.status, func.count(HumanReviewTask.id))
        .group_by(HumanReviewTask.status)
    )
    counts = {row[0].value: row[1] for row in result.all()}
    total = sum(counts.values())
    return ReviewTaskSummary(
        total=total,
        pending=counts.get("pending", 0),
        in_progress=counts.get("in_progress", 0),
        completed=counts.get("completed", 0),
        cancelled=counts.get("cancelled", 0),
    )


@router.get("/{task_id}", response_model=ReviewTaskOut)
async def get_review_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(VIEW_QUEUE)),
):
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=ReviewTaskOut)
async def update_review_task(
    task_id: UUID,
    payload: ReviewTaskUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE_ACTION)),
):
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    details: dict = {"task_id": str(task_id)}
    if payload.status is not None:
        details["status_from"] = task.status.value
        details["status_to"] = payload.status.value
        task.status = payload.status
    if payload.assigned_to is not None:
        task.assigned_to = payload.assigned_to
        details["assigned_to"] = str(payload.assigned_to)
    if payload.notes is not None:
        task.notes = payload.notes

    await record_event(db, actor=actor, action="review_task.updated", details=details)
    await db.commit()
    await db.refresh(task)
    return task
