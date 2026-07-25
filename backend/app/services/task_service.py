"""Task/escalation service — backs the Escalations kanban (design 4) and task detail (design 5).

The Task model from feature/task-call-models has source (email|call), priority,
and status (pending|in_progress|completed|escalated). The Escalations page maps
these statuses to kanban columns: pending→Submitted, in_progress→Under review,
escalated→Escalated, completed→Resolved.

Additional fields not in the model (task description, timeline, RBAC violation
flag, SLA) are derived or placeholder — the model is the floor, the service
builds up from it.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.audit_service import record_event

# Kanban column order for the escalations board.
KANBAN_COLUMNS = [
    TaskItemStatus.PENDING,       # Submitted
    TaskItemStatus.IN_PROGRESS,   # Under review
    TaskItemStatus.ESCALATED,     # Escalated
    TaskItemStatus.COMPLETED,     # Resolved
]


class TaskNotFoundError(Exception):
    """Raised when task_id doesn't reference an existing task."""


class TaskStateError(Exception):
    """Raised on an illegal state transition."""


_LEGAL_TRANSITIONS: dict[TaskItemStatus, set[TaskItemStatus]] = {
    TaskItemStatus.PENDING: {TaskItemStatus.IN_PROGRESS, TaskItemStatus.ESCALATED, TaskItemStatus.COMPLETED},
    TaskItemStatus.IN_PROGRESS: {TaskItemStatus.ESCALATED, TaskItemStatus.COMPLETED},
    TaskItemStatus.ESCALATED: {TaskItemStatus.IN_PROGRESS, TaskItemStatus.COMPLETED},
    TaskItemStatus.COMPLETED: set(),
}


async def create_task(db: AsyncSession, payload: TaskCreate, actor: User) -> Task:
    task = Task(
        case_id=payload.case_id,
        assigned_to=payload.assigned_to,
        source=payload.source,
        priority=payload.priority,
        status=TaskItemStatus.PENDING,
    )
    db.add(task)
    await db.flush()

    await record_event(
        db,
        case_id=payload.case_id,
        actor=actor,
        action="task.created",
        details={
            "task_id": str(task.id),
            "source": payload.source.value,
            "priority": payload.priority.value,
        },
    )
    await db.commit()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: UUID) -> Task | None:
    return await db.get(Task, task_id)


async def list_tasks(
    db: AsyncSession,
    *,
    status: list[TaskItemStatus] | None = None,
    priority: list[TaskPriority] | None = None,
    assigned_to: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Task], int]:
    filters = []
    if status:
        filters.append(Task.status.in_(status))
    if priority:
        filters.append(Task.priority.in_(priority))
    if assigned_to is not None:
        filters.append(Task.assigned_to == assigned_to)

    stmt = select(Task)
    count_stmt = select(func.count()).select_from(Task)
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def list_tasks_by_column(db: AsyncSession) -> dict[str, list[Task]]:
    """Return tasks grouped by kanban column status, for the escalations board."""
    result = await db.execute(
        select(Task).order_by(Task.created_at.desc()).limit(200)
    )
    tasks = list(result.scalars().all())

    columns: dict[str, list[Task]] = {s.value: [] for s in KANBAN_COLUMNS}
    for task in tasks:
        columns[task.status.value].append(task)
    return columns


async def update_task(
    db: AsyncSession, task_id: UUID, payload: TaskUpdate, actor: User
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"No task with id {task_id}")

    details: dict = {"task_id": str(task_id)}

    if payload.status is not None and payload.status != task.status:
        if payload.status not in _LEGAL_TRANSITIONS[task.status]:
            raise TaskStateError(
                f"Cannot move task from '{task.status.value}' to '{payload.status.value}'"
            )
        details["status_from"] = task.status.value
        details["status_to"] = payload.status.value
        task.status = payload.status

    if payload.assigned_to is not None:
        details["assigned_to"] = str(payload.assigned_to)
        task.assigned_to = payload.assigned_to

    if payload.priority is not None:
        details["priority"] = payload.priority.value
        task.priority = payload.priority

    await record_event(
        db,
        case_id=task.case_id,
        actor=actor,
        action="task.updated",
        details=details,
    )
    await db.commit()
    await db.refresh(task)
    return task


async def column_counts(db: AsyncSession) -> dict[str, int]:
    """Count per status for the kanban column headers."""
    result = await db.execute(
        select(Task.status, func.count(Task.id)).group_by(Task.status)
    )
    counts = {s.value: 0 for s in KANBAN_COLUMNS}
    for status, count in result.all():
        counts[status.value] = count
    return counts
