"""Reviewer queue service (FR-TASK-02 / FR-GOV-02's escalation surface).

Operates on HumanReviewTask (app/models/human_review.py), the low-confidence/
escalated tier's work queue. Distinct from ApprovalRequest
(app/services/approval_service.py), which is a binary governance decision,
not a claim/work queue — see
docs/superpowers/specs/2026-07-24-fr-gov-01-approval-gate-design.md section 3.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.user import User, UserRole


class HumanReviewTaskNotFoundError(Exception):
    """Raised when task_id doesn't reference an existing HumanReviewTask."""


class HumanReviewTaskWrongStateError(Exception):
    """Raised when claim/complete is called on a task not in the expected state."""


class HumanReviewTaskWrongRoleError(Exception):
    """Raised when actor.role doesn't match the task's target_role."""


async def list_tasks(
    db: AsyncSession,
    target_role: UserRole,
    status: TaskStatus | None = None,
    task_type: TaskType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[HumanReviewTask], int]:
    query = select(HumanReviewTask).where(HumanReviewTask.target_role == target_role)
    count_query = (
        select(func.count())
        .select_from(HumanReviewTask)
        .where(HumanReviewTask.target_role == target_role)
    )
    if status is not None:
        query = query.where(HumanReviewTask.status == status)
        count_query = count_query.where(HumanReviewTask.status == status)
    if task_type is not None:
        query = query.where(HumanReviewTask.task_type == task_type)
        count_query = count_query.where(HumanReviewTask.task_type == task_type)

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(HumanReviewTask.created_at).limit(limit).offset(offset)
    items = (await db.execute(query)).scalars().all()
    return list(items), total


async def claim_task(db: AsyncSession, task_id: UUID, actor: User) -> HumanReviewTask:
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HumanReviewTaskNotFoundError(f"No human review task with id {task_id}")
    if task.target_role != actor.role:
        raise HumanReviewTaskWrongRoleError(
            f"Task {task_id} is targeted at role '{task.target_role}', "
            f"actor holds role '{actor.role.value}'"
        )
    if task.status != TaskStatus.PENDING:
        raise HumanReviewTaskWrongStateError(f"Task {task_id} is '{task.status.value}', not pending")

    task.status = TaskStatus.IN_PROGRESS
    task.assigned_to = actor.id
    await db.commit()
    await db.refresh(task)
    return task


async def complete_task(
    db: AsyncSession, task_id: UUID, actor: User, notes: str | None = None
) -> HumanReviewTask:
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HumanReviewTaskNotFoundError(f"No human review task with id {task_id}")
    if task.target_role != actor.role:
        raise HumanReviewTaskWrongRoleError(
            f"Task {task_id} is targeted at role '{task.target_role}', "
            f"actor holds role '{actor.role.value}'"
        )
    if task.status != TaskStatus.IN_PROGRESS:
        raise HumanReviewTaskWrongStateError(
            f"Task {task_id} is '{task.status.value}', not in progress"
        )

    task.status = TaskStatus.COMPLETED
    task.notes = notes
    await db.commit()
    await db.refresh(task)
    return task
