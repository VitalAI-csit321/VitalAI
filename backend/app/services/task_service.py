from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import MANAGE_CASES, effective_permissions
from app.auth.scoping import assigned_patient_ids_subquery
from app.models.call import Call
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.task_comment import TaskComment
from app.models.user import User, UserRole
from app.schemas.task import TaskCommentCreate, TaskCreate, TaskOut, TaskUpdate
from app.services.audit_service import record_event
from app.services.task_routing_rules import resolve_target_role


class CaseNotFoundError(Exception):
    """Raised when a task references an intake case that does not exist."""


class AssigneeNotFoundError(Exception):
    """Raised when assigned_to does not reference an existing user."""


class TaskNotFoundError(Exception):
    """Raised when task_id doesn't reference an existing Task."""


class TaskAlreadyEscalatedError(Exception):
    """Raised when a task that is already escalated is escalated again."""


class TaskForbiddenError(Exception):
    """Raised when actor lacks row-level access to a task they otherwise
    have route-level permission to act on (mirrors inbox_service's
    _visible_tasks scoping: not MANAGE_CASES, task.target_role doesn't
    match the actor's role, or the actor is a doctor unassigned to the
    task's patient).
    """


async def _check_task_access(db: AsyncSession, task: Task, actor: User) -> None:
    if MANAGE_CASES in effective_permissions(actor):
        return
    if task.target_role is not None and task.target_role != actor.role:
        raise TaskForbiddenError(f"Task {task.id} is not in your queue")
    if actor.role == UserRole.DOCTOR:
        assigned = await db.execute(
            select(IntakeCase.id).where(
                IntakeCase.id == task.case_id,
                IntakeCase.patient_id.in_(assigned_patient_ids_subquery(actor.id)),
            )
        )
        if assigned.scalar() is None:
            raise TaskForbiddenError(f"Task {task.id} is not assigned to you")


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


async def _identify(db: AsyncSession, task: Task) -> tuple[str | None, str | None]:
    """Subject/from_name for the linked Email or Call, so a list of tasks
    can be told apart; the Task row itself carries no human-readable
    content, only foreign keys and enums.
    """
    if task.source == TaskSource.EMAIL:
        result = await db.execute(select(Email).where(Email.case_id == task.case_id))
        email = result.scalars().first()
        return (email.subject, email.sender) if email is not None else (None, None)

    call = await db.get(Call, task.call_id) if task.call_id else None
    if call is None:
        return None, None
    return f"Call from {call.phone_number}", call.phone_number


async def list_tasks(db: AsyncSession) -> list[TaskOut]:
    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    tasks = list(result.scalars().all())

    out = []
    for task in tasks:
        subject, from_name = await _identify(db, task)
        out.append(
            TaskOut.model_validate(task, from_attributes=True).model_copy(
                update={"subject": subject, "from_name": from_name}
            )
        )
    return out


async def update_task(db: AsyncSession, task_id: UUID, payload: TaskUpdate, actor: User) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Task {task_id} not found")

    if payload.assigned_to is not None:
        assignee = await db.get(User, payload.assigned_to)
        if assignee is None:
            raise AssigneeNotFoundError(f"User {payload.assigned_to} not found")

    changes: dict[str, str] = {}
    if payload.status is not None:
        task.status = payload.status
        changes["status"] = payload.status.value
    if payload.assigned_to is not None:
        task.assigned_to = payload.assigned_to
        changes["assigned_to"] = str(payload.assigned_to)
    if payload.priority is not None:
        task.priority = payload.priority
        changes["priority"] = payload.priority.value

    await record_event(
        db,
        case_id=task.case_id,
        actor=actor,
        action="task.updated",
        details={"task_id": str(task.id), **changes},
    )
    await db.commit()
    await db.refresh(task)
    return task


async def add_comment(
    db: AsyncSession, task_id: UUID, payload: TaskCommentCreate, actor: User
) -> TaskComment:
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Task {task_id} not found")

    comment = TaskComment(task_id=task_id, author_id=actor.id, body=payload.body)
    db.add(comment)
    await db.flush()

    await record_event(
        db,
        case_id=task.case_id,
        actor=actor,
        action="task.commented",
        details={"task_id": str(task_id), "comment_id": str(comment.id)},
    )
    await db.commit()
    await db.refresh(comment)
    return comment


async def list_comments(db: AsyncSession, task_id: UUID) -> list[TaskComment]:
    result = await db.execute(
        select(TaskComment)
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc())
    )
    return list(result.scalars().all())


async def escalate_task(db: AsyncSession, task_id: UUID, reason: str | None, actor: User) -> Task:
    """Mark a task ESCALATED and bump it to URGENT priority. Works for any
    task regardless of source; the same lifecycle action call_service's
    escalate_call() applies specifically to call-sourced tasks, generalized
    here so email-sourced (and manually created) tasks have an equivalent.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Task {task_id} not found")
    await _check_task_access(db, task, actor)
    if task.status == TaskItemStatus.ESCALATED:
        raise TaskAlreadyEscalatedError(f"Task {task_id} is already escalated")

    task.status = TaskItemStatus.ESCALATED
    task.priority = TaskPriority.URGENT
    await db.flush()

    await record_event(
        db,
        case_id=task.case_id,
        actor=actor,
        action="task.escalated",
        details={"task_id": str(task.id), "reason": reason},
    )
    await db.commit()
    await db.refresh(task)
    return task


async def archive_task(db: AsyncSession, task_id: UUID, actor: User) -> Task:
    """Mark a task COMPLETED. Removes it from the RBAC-scoped inbox feed
    (inbox_service excludes COMPLETED tasks), same as archiving an email.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Task {task_id} not found")
    await _check_task_access(db, task, actor)

    task.status = TaskItemStatus.COMPLETED
    await db.flush()

    await record_event(
        db,
        case_id=task.case_id,
        actor=actor,
        action="task.archived",
        details={"task_id": str(task.id)},
    )
    await db.commit()
    await db.refresh(task)
    return task


async def override_task(
    db: AsyncSession, task_id: UUID, category: TaskCategory, reason: str, actor: User
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Task {task_id} not found")

    previous_category = task.category.value if task.category else None
    new_target_role = resolve_target_role(category)

    task.category = category
    task.target_role = new_target_role
    await db.flush()

    await record_event(
        db,
        case_id=task.case_id,
        actor=actor,
        action="task.override_recorded",
        details={
            "task_id": str(task.id),
            "previous_category": previous_category,
            "new_category": category.value,
            "new_target_role": new_target_role.value,
            "reason": reason,
        },
    )
    await db.commit()
    await db.refresh(task)
    return task
