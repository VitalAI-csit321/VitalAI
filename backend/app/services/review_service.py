"""Human review task service — backs the Administrative Review Queue.

The HumanReviewTask model and its migration (0004) already existed with no code
behind them; this is that missing layer. Follows the same conventions as the
other services: mutations write an audit event and commit atomically with it.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.user import User
from app.schemas.review import ReviewTaskCreate, ReviewTaskUpdate
from app.services.audit_service import record_event


class ReviewStateError(Exception):
    """Raised when a review task state transition is illegal."""


# A task may move forward, or be cancelled from any open state. Terminal states
# have no outgoing transitions — reopening a completed review would silently
# invalidate whatever decision was recorded against it.
_LEGAL_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}


async def create_task(db: AsyncSession, payload: ReviewTaskCreate, actor: User) -> HumanReviewTask:
    task = HumanReviewTask(
        case_id=payload.case_id,
        triage_id=payload.triage_id,
        task_type=payload.task_type,
        status=TaskStatus.PENDING,
        notes=payload.notes,
    )
    db.add(task)
    await db.flush()

    await record_event(
        db,
        case_id=payload.case_id,
        actor=actor,
        action="review_task.created",
        details={"task_id": str(task.id), "task_type": payload.task_type.value},
    )
    await db.commit()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: UUID) -> HumanReviewTask | None:
    return await db.get(HumanReviewTask, task_id)


async def list_tasks(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: list[TaskStatus] | None = None,
    task_type: list[TaskType] | None = None,
    assigned_to: UUID | None = None,
    case_id: UUID | None = None,
) -> tuple[list[HumanReviewTask], int]:
    """Return (page_of_tasks, total_matching_count). Oldest first — a review
    queue is worked front-to-back, unlike the newest-first case list."""
    filters = []
    if status:
        filters.append(HumanReviewTask.status.in_(status))
    if task_type:
        filters.append(HumanReviewTask.task_type.in_(task_type))
    if assigned_to is not None:
        filters.append(HumanReviewTask.assigned_to == assigned_to)
    if case_id is not None:
        filters.append(HumanReviewTask.case_id == case_id)

    count_stmt = select(func.count()).select_from(HumanReviewTask)
    page_stmt = select(HumanReviewTask)
    if filters:
        count_stmt = count_stmt.where(*filters)
        page_stmt = page_stmt.where(*filters)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(
        page_stmt.order_by(HumanReviewTask.created_at.asc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def update_task(
    db: AsyncSession, task_id: UUID, payload: ReviewTaskUpdate, actor: User
) -> HumanReviewTask | None:
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        return None

    details: dict = {"task_id": str(task_id)}

    if payload.status is not None and payload.status != task.status:
        if payload.status not in _LEGAL_TRANSITIONS[task.status]:
            raise ReviewStateError(
                f"Cannot move review task from '{task.status.value}' to '{payload.status.value}'."
            )
        details["status_from"] = task.status.value
        details["status_to"] = payload.status.value
        task.status = payload.status

    if payload.assigned_to is not None and payload.assigned_to != task.assigned_to:
        assignee = await db.get(User, payload.assigned_to)
        if assignee is None:
            raise ReviewStateError(f"User {payload.assigned_to} does not exist.")
        details["assigned_to"] = str(payload.assigned_to)
        task.assigned_to = payload.assigned_to

    if payload.notes is not None:
        task.notes = payload.notes
        details["notes_updated"] = True

    await record_event(
        db, case_id=task.case_id, actor=actor, action="review_task.updated", details=details
    )
    await db.commit()
    await db.refresh(task)
    return task


async def queue_counts(db: AsyncSession) -> dict[str, int]:
    """Open task count per task_type — drives the queue page's tab badges."""
    result = await db.execute(
        select(HumanReviewTask.task_type, func.count(HumanReviewTask.id))
        .where(HumanReviewTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]))
        .group_by(HumanReviewTask.task_type)
    )
    counts = {task_type.value: 0 for task_type in TaskType}
    for task_type, count in result.all():
        counts[task_type.value] = count
    return counts
