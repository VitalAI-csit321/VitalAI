from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase
from app.models.task import Task, TaskItemStatus
from app.models.user import User
from app.schemas.task import TaskCreate
from app.services.audit_service import record_event


class CaseNotFoundError(Exception):
    """Raised when a task references an intake case that does not exist."""


class AssigneeNotFoundError(Exception):
    """Raised when assigned_to does not reference an existing user."""


async def create_task(db: AsyncSession, payload: TaskCreate, actor: User) -> Task:
    case = await db.get(IntakeCase, payload.case_id)
    if case is None:
        raise CaseNotFoundError(f"Case {payload.case_id} not found")

    if payload.assigned_to is not None:
        assignee = await db.get(User, payload.assigned_to)
        if assignee is None:
            raise AssigneeNotFoundError(f"User {payload.assigned_to} not found")

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
        case_id=case.id,
        actor=actor,
        action="task.created",
        details={
            "task_id": str(task.id),
            "source": task.source.value,
            "priority": task.priority.value,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
            "manual_entry": True,
        },
    )
    await db.commit()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: UUID) -> Task | None:
    return await db.get(Task, task_id)


async def list_tasks(db: AsyncSession) -> list[Task]:
    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    return list(result.scalars().all())
