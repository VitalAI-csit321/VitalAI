"""Reviewer queue service (FR-TASK-02 / FR-GOV-02's escalation surface).

Operates on HumanReviewTask (app/models/human_review.py), the low-confidence/
escalated tier's work queue. Distinct from ApprovalRequest
(app/services/approval_service.py), which is a binary governance decision,
not a claim/work queue; see
docs/superpowers/specs/2026-07-24-fr-gov-01-approval-gate-design.md section 3.

A DOCTOR-targeted task is actionable by the doctor it is already assigned_to
(e.g. one they previously claimed), or otherwise only by a doctor actually
assigned to the task's case's patient (app/auth/scoping.py's
assigned_patient_ids_subquery(), the same row-level scoping Phase 3 built for
/patients, /consent, /rag/query), see
docs/superpowers/specs/2026-07-25-governance-follow-ups-design.md section 1,
or by the doctor who logged that case (_doctor_case_filter()).

Visibility and action authority are otherwise scoped by can_act(): own role
only, except an operator also works the front desk's items (D6), a doctor
only for items assigned to them or about their patients, and actors holding
VIEW_ALL_QUEUES (app/auth/permissions.py) who see and can act on every role's
queue - currently ADMIN only. See can_act().
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import VIEW_ALL_QUEUES, effective_permissions
from app.auth.scoping import assigned_patient_ids_subquery
from app.config import settings
from app.models.audit import AuditEvent
from app.models.case import IntakeCase, IntakeStatus
from app.models.episode import Episode
from app.models.human_review import HumanReviewTask, TaskPriority, TaskStatus, TaskType
from app.models.patient import Patient
from app.models.task import Task, TaskCategory
from app.models.user import User, UserRole
from app.services import email_service, episode_service, review_routing, task_service
from app.services.audit_service import record_event
from app.services.task_routing_rules import resolve_target_role

_ACTIONABLE = (TaskStatus.IN_PROGRESS, TaskStatus.ESCALATED)
# D11: one level up. The admin is the top.
_NEXT_LEVEL = {
    UserRole.FRONT_DESK: UserRole.OPERATOR,
    UserRole.DOCTOR: UserRole.OPERATOR,
    UserRole.OPERATOR: UserRole.ADMIN,
}
# D7: what the queue shows when an item has no named owner yet.
_QUEUE_LABEL: dict[UserRole | None, str] = {
    UserRole.FRONT_DESK: "Front desk queue",
    UserRole.OPERATOR: "Operator queue",
    UserRole.ADMIN: "Admin queue",
    UserRole.DOCTOR: "Doctor queue",
}


def due_at(item: HumanReviewTask) -> datetime:
    """D7: over SLA past this. High priority gets the shorter, editable window."""
    hours = (
        settings.review_sla_hours_high
        if item.priority == TaskPriority.HIGH
        else settings.review_sla_hours_default
    )
    return item.created_at + timedelta(hours=hours)


class HumanReviewTaskNotFoundError(Exception):
    """Raised when task_id doesn't reference an existing HumanReviewTask."""


class HumanReviewTaskWrongStateError(Exception):
    """Raised when claim/complete is called on a task not in the expected state."""


class HumanReviewTaskWrongRoleError(Exception):
    """Raised when actor.role doesn't match the task's target_role, or (for a
    doctor) when actor isn't assigned to the task's case's patient."""


class HumanReviewInvalidChoiceError(Exception):
    """A choice the item did not offer (a patient, a doctor)."""


def _doctor_case_filter(doctor_id: UUID):
    """Cases a doctor may see and act on: their assigned patients' cases, plus
    the patient-less cases they logged themselves via create_task(). The
    creator comes from the case's intake.created audit event (append-only)."""
    created_by_doctor = select(AuditEvent.case_id).where(
        AuditEvent.action == "intake.created", AuditEvent.actor_id == doctor_id
    )
    return or_(
        IntakeCase.patient_id.in_(assigned_patient_ids_subquery(doctor_id)),
        IntakeCase.id.in_(created_by_doctor),
    )


async def list_tasks(
    db: AsyncSession,
    actor: User,
    status: TaskStatus | None = None,
    task_type: TaskType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[HumanReviewTask], int]:
    query = select(HumanReviewTask)
    count_query = select(func.count()).select_from(HumanReviewTask)
    query = _scope(query, actor)
    count_query = _scope(count_query, actor)
    if status is not None:
        query = query.where(HumanReviewTask.status == status)
        count_query = count_query.where(HumanReviewTask.status == status)
    if task_type is not None:
        query = query.where(HumanReviewTask.task_type == task_type)
        count_query = count_query.where(HumanReviewTask.task_type == task_type)

    total = (await db.execute(count_query)).scalar_one()
    # Open items first, oldest first (SLA order), then closed ones newest
    # first, so closed history never pushes new work off a limited page.
    is_open = HumanReviewTask.status.in_(review_routing.OPEN_STATUSES)
    query = (
        query.order_by(
            case((is_open, HumanReviewTask.created_at)).asc().nulls_last(),
            HumanReviewTask.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    items = (await db.execute(query)).scalars().all()
    return list(items), total


async def describe_tasks(db: AsyncSession, tasks: list[HumanReviewTask]) -> dict[UUID, dict]:
    """What the queue shows beside each task, keyed by task id: the case's
    reason and patient, who logged it (its intake.created audit event, which
    the case row itself doesn't record) and the owner's name."""
    case_ids = {t.case_id for t in tasks}
    cases = {
        c.id: c
        for c in (await db.scalars(select(IntakeCase).where(IntakeCase.id.in_(case_ids)))).all()
    }
    created = {
        e.case_id: e
        for e in (
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.case_id.in_(case_ids), AuditEvent.action == "intake.created"
                )
            )
        ).all()
    }
    user_ids = {e.actor_id for e in created.values() if e.actor_id} | {
        t.assigned_to for t in tasks if t.assigned_to
    }
    names: dict[UUID | None, str] = dict(
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids))))
        .tuples()
        .all()
    )

    candidate_ids = {
        UUID(c)
        for t in tasks
        if t.task_type == TaskType.IDENTITY_REVIEW
        for c in (t.details or {}).get("candidates", [])
    }
    patients = {
        str(p_id): {"id": str(p_id), "name": name, "dob": dob.isoformat() if dob else None}
        for p_id, name, dob in (
            await db.execute(
                select(Patient.id, Patient.name, Patient.dob).where(Patient.id.in_(candidate_ids))
            )
        ).tuples()
    }

    # Cases (M4): the case a "Close this case?" item is about, and the open
    # cases a "Which case?" item offers.
    episode_ids = {t.episode_id for t in tasks if t.episode_id} | {
        UUID(c)
        for t in tasks
        if t.task_type == TaskType.CASE_CHOICE
        for c in (t.details or {}).get("candidates", [])
    }
    episodes = {
        e.id: e
        for e in (await db.scalars(select(Episode).where(Episode.id.in_(episode_ids)))).all()
    }
    episode_patients: dict[UUID, str] = dict(
        (
            await db.execute(
                select(Patient.id, Patient.name).where(
                    Patient.id.in_({e.patient_id for e in episodes.values()})
                )
            )
        )
        .tuples()
        .all()
    )

    def _candidate(episode_id: str) -> dict | None:
        e = episodes.get(UUID(episode_id))
        return (
            {"id": episode_id, "title": e.title, "last_activity_at": e.last_activity_at}
            if e
            else None
        )

    details = {}
    for t in tasks:
        # An item about a case (case_close) has no contact.
        case = cases.get(t.case_id) if t.case_id else None
        event = created.get(t.case_id) if t.case_id else None
        episode = episodes.get(t.episode_id) if t.episode_id else None
        details[t.id] = {
            "contact_reason": case.contact_reason if case else None,
            "patient_name": case.patient_name
            if case
            else (episode_patients.get(episode.patient_id) if episode else None),
            "case_title": episode.title if episode else None,
            "case_candidates": [
                c for c in map(_candidate, (t.details or {}).get("candidates", [])) if c is not None
            ]
            if t.task_type == TaskType.CASE_CHOICE
            else None,
            "created_by": (names.get(event.actor_id) or event.actor_label) if event else None,
            "assigned_to_name": names.get(t.assigned_to),
            "owner_label": names.get(t.assigned_to)
            or _QUEUE_LABEL.get(t.target_role, "Unassigned"),
            "channel": case.contact_channel if case else None,
            "due_at": due_at(t),
            "candidates": [
                patients[c] for c in (t.details or {}).get("candidates", []) if c in patients
            ]
            if t.task_type == TaskType.IDENTITY_REVIEW
            else None,
        }
    return details


async def count_tasks_by_day(
    db: AsyncSession, actor: User, week_start: datetime
) -> dict[date, int]:
    """Task volume per day for the Mon-Sun week starting at week_start (UTC
    midnight). Bucketed in Python rather than a DB date_trunc so this behaves
    identically on SQLite (the test default) and Postgres, matching this
    module's existing SQLite/Postgres portability elsewhere in the codebase.

    Same visibility scoping as list_tasks -- a doctor's dashboard should not
    reflect volume from queues or patients they cannot otherwise see.
    """
    week_end = week_start + timedelta(days=7)
    query = select(HumanReviewTask.created_at).where(
        HumanReviewTask.created_at >= week_start,
        HumanReviewTask.created_at < week_end,
    )
    query = _scope(query, actor)

    timestamps = (await db.execute(query)).scalars().all()
    counts: dict[date, int] = {}
    for ts in timestamps:
        day = ts.date()
        counts[day] = counts.get(day, 0) + 1
    return counts


async def create_task(
    db: AsyncSession,
    actor: User,
    *,
    task_type: TaskType,
    contact_reason: str,
    priority: TaskPriority = TaskPriority.MEDIUM,
    assigned_to: UUID | None = None,
    reviewed: bool = False,
    notes: str | None = None,
) -> HumanReviewTask:
    """Manually log an independent case + review task (FR-TASK-ADD).

    Unlike system-generated tasks (triage/routing), this isn't linked to an
    existing patient - `IntakeCase.patient_id` is nullable precisely for this
    standalone case. `target_role` defaults to the creating actor's own role
    so the task is immediately visible in their own queue (list_tasks scopes
    by `target_role == actor.role`, except for actors holding VIEW_ALL_QUEUES).
    """
    case = IntakeCase(
        patient_id=None,
        contact_reason=contact_reason,
        contact_channel="manual",
        status=IntakeStatus.RECEIVED,
    )
    db.add(case)
    await db.flush()

    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="intake.created",
        details={"channel": "manual"},
    )

    task = HumanReviewTask(
        case_id=case.id,
        task_type=task_type,
        priority=priority,
        target_role=actor.role,
        assigned_to=assigned_to,
        status=TaskStatus.COMPLETED if reviewed else TaskStatus.PENDING,
        notes=notes,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _doctor_sees_episode(db: AsyncSession, episode_id: UUID | None, doctor_id: UUID) -> bool:
    """An item about a case (no contact): the case's patient is assigned to them."""
    return (
        episode_id is not None
        and await db.scalar(
            select(Episode.id).where(
                Episode.id == episode_id,
                Episode.patient_id.in_(assigned_patient_ids_subquery(doctor_id)),
            )
        )
        is not None
    )


async def _doctor_sees_case(db: AsyncSession, case_id: UUID, doctor_id: UUID) -> bool:
    return (
        await db.scalar(
            select(IntakeCase.id).where(IntakeCase.id == case_id, _doctor_case_filter(doctor_id))
        )
    ) is not None


async def can_act(db: AsyncSession, actor: User, item: HumanReviewTask) -> bool:
    """Spec section 7. Admin: everything. Own role: yes, and a doctor only for
    items assigned to them or about their patients. The operator also works
    the front desk's items (D6)."""
    if VIEW_ALL_QUEUES in effective_permissions(actor):
        return True
    if item.target_role == actor.role:
        if actor.role != UserRole.DOCTOR:
            return True
        if item.assigned_to == actor.id:
            return True
        if item.case_id is not None:
            return await _doctor_sees_case(db, item.case_id, actor.id)
        return await _doctor_sees_episode(db, item.episode_id, actor.id)
    return actor.role == UserRole.OPERATOR and item.target_role == UserRole.FRONT_DESK


async def is_clinical(db: AsyncSession, item: HumanReviewTask) -> bool:
    """Clinical if either the category recorded at draft time (item.details,
    set by approval_service.create_approval_request) or the inbox task's
    current category is clinical. An operator can retarget a task's category
    after the draft is drawn up (POST /tasks/{id}/override); the drafted
    category still counts so that can't launder a clinical reply through a
    relabel. No inbox task to check at all fails closed (clinical)."""
    task = await db.get(Task, item.inbox_task_id) if item.inbox_task_id else None
    if task is None:
        return True
    clinical = {c.value for c in email_service._clinical_categories()}
    current = task.category.value if task.category else None
    drafted = (item.details or {}).get("category")
    return current in clinical or drafted in clinical


async def can_approve(db: AsyncSession, actor: User, item: HumanReviewTask) -> bool:
    """can_act, except that clinical text is approved only by a doctor or the admin."""
    if not await can_act(db, actor, item):
        return False
    if actor.role == UserRole.DOCTOR or VIEW_ALL_QUEUES in effective_permissions(actor):
        return True
    return not await is_clinical(db, item)


async def item_for_approval(db: AsyncSession, approval_id: UUID) -> HumanReviewTask | None:
    return (
        await db.execute(
            select(HumanReviewTask)
            .where(HumanReviewTask.approval_id == approval_id)
            .order_by(HumanReviewTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _require_can_act(db: AsyncSession, task: HumanReviewTask, actor: User) -> None:
    if not await can_act(db, actor, task):
        raise HumanReviewTaskWrongRoleError(f"Task {task.id} is not yours to act on")


async def _audit(
    db: AsyncSession, actor: User, task: HumanReviewTask, action: str, **extra
) -> None:
    await record_event(
        db,
        actor=actor,
        case_id=task.case_id,
        action=action,
        details={"review_id": str(task.id), "kind": task.task_type.value, **extra},
    )


async def _actionable(db: AsyncSession, task_id: UUID, actor: User) -> HumanReviewTask:
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HumanReviewTaskNotFoundError(f"No human review task with id {task_id}")
    await _require_can_act(db, task, actor)
    if task.status not in _ACTIONABLE:
        raise HumanReviewTaskWrongStateError(f"Task {task_id} is '{task.status.value}', not open")
    return task


def _not_a_draft(task: HumanReviewTask) -> None:
    # Only approve/reject resume the paused agent thread and settle the approval.
    if task.task_type == TaskType.DRAFT_APPROVAL:
        raise HumanReviewTaskWrongStateError("Approve or reject the draft instead")


def _scope(query, actor: User):
    """Same rules as can_act, as a query filter."""
    if VIEW_ALL_QUEUES in effective_permissions(actor):
        return query
    roles = [actor.role, UserRole.FRONT_DESK] if actor.role == UserRole.OPERATOR else [actor.role]
    query = query.where(HumanReviewTask.target_role.in_(roles))
    if actor.role == UserRole.DOCTOR:
        # Outer joins: an item about a case (CASE_CLOSE) has no contact.
        query = (
            query.outerjoin(IntakeCase, HumanReviewTask.case_id == IntakeCase.id)
            .outerjoin(Episode, HumanReviewTask.episode_id == Episode.id)
            .where(
                or_(
                    HumanReviewTask.assigned_to == actor.id,
                    _doctor_case_filter(actor.id),
                    Episode.patient_id.in_(assigned_patient_ids_subquery(actor.id)),
                )
            )
        )
    return query


async def claim_task(db: AsyncSession, task_id: UUID, actor: User) -> HumanReviewTask:
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HumanReviewTaskNotFoundError(f"No human review task with id {task_id}")
    await _require_can_act(db, task, actor)
    if task.status != TaskStatus.PENDING:
        raise HumanReviewTaskWrongStateError(
            f"Task {task_id} is '{task.status.value}', not pending"
        )

    task.status = TaskStatus.IN_PROGRESS
    task.assigned_to = actor.id
    await _audit(db, actor, task, "review.claimed")
    await db.commit()
    await db.refresh(task)
    return task


async def complete_task(
    db: AsyncSession, task_id: UUID, actor: User, notes: str | None = None
) -> HumanReviewTask:
    task = await _actionable(db, task_id, actor)
    _not_a_draft(task)

    task.status = TaskStatus.COMPLETED
    task.notes = notes
    await _audit(db, actor, task, "review.completed", note=notes)
    await db.commit()
    await db.refresh(task)
    return task


async def reject_task(
    db: AsyncSession, task_id: UUID, actor: User, notes: str | None = None
) -> HumanReviewTask:
    task = await _actionable(db, task_id, actor)
    _not_a_draft(task)

    task.status = TaskStatus.CANCELLED
    task.notes = notes
    await _audit(db, actor, task, "review.dismissed", note=notes)
    await db.commit()
    await db.refresh(task)
    return task


async def escalate_task(
    db: AsyncSession, task_id: UUID, actor: User, notes: str | None = None
) -> HumanReviewTask:
    task = await _actionable(db, task_id, actor)
    to_role = _NEXT_LEVEL.get(actor.role)
    if to_role is None:
        raise HumanReviewTaskWrongRoleError("The admin is the top level: nothing to escalate to")

    from_role = task.target_role
    task.status = TaskStatus.ESCALATED
    task.priority = TaskPriority.HIGH
    task.target_role = to_role
    task.assigned_to = None  # it leaves the previous owner's queue
    task.details = {
        **(task.details or {}),
        "escalation": {"by": actor.full_name, "by_role": actor.role.value, "note": notes},
    }

    inbox = await db.get(Task, task.inbox_task_id) if task.inbox_task_id else None
    if inbox is not None:
        await task_service.mark_escalated(db, inbox, actor=actor, reason=notes)

    await _audit(
        db,
        actor,
        task,
        "review.escalated",
        note=notes,
        from_role=from_role.value if from_role else None,
        to_role=to_role.value,
    )
    await db.commit()
    await db.refresh(task)
    return task


async def _open_item(
    db: AsyncSession, task_id: UUID, actor: User, kinds: set[TaskType]
) -> HumanReviewTask:
    task = await db.get(HumanReviewTask, task_id)
    if task is None:
        raise HumanReviewTaskNotFoundError(f"No human review task with id {task_id}")
    await _require_can_act(db, task, actor)
    if task.status not in review_routing.OPEN_STATUSES:
        raise HumanReviewTaskWrongStateError(f"Task {task_id} is '{task.status.value}', not open")
    if task.task_type not in kinds:
        raise HumanReviewTaskWrongStateError(f"Not offered on a {task.task_type.value} item")
    return task


async def reroute(
    db: AsyncSession, task_id: UUID, actor: User, category: TaskCategory
) -> HumanReviewTask:
    task = await _open_item(db, task_id, actor, {TaskType.ROUTING_REVIEW, TaskType.INTENT_REVIEW})
    inbox = await db.get(Task, task.inbox_task_id) if task.inbox_task_id else None
    if inbox is None:
        raise HumanReviewTaskWrongStateError("The message is gone")
    previous = inbox.category.value if inbox.category else None
    inbox.category = category
    inbox.target_role = resolve_target_role(category)
    # What intake does for these categories (D9, D10).
    if category == TaskCategory.URGENT_EMERGENCY:
        await task_service.mark_escalated(
            db, inbox, actor=actor, reason="rerouted: urgent_category"
        )
    elif category == TaskCategory.COMPLAINT_ESCALATION:
        await review_routing.open_item(
            db,
            kind=TaskType.COMPLAINT_REVIEW,
            inbox_task=inbox,
            reason=task_service.COMPLAINT_REASON,
            actor=actor,
            priority=TaskPriority.HIGH,
        )
    task.status = TaskStatus.COMPLETED
    await _audit(
        db,
        actor,
        task,
        "review.rerouted",
        previous_category=previous,
        new_category=category.value,
        new_target_role=inbox.target_role.value,
    )
    await db.commit()
    await db.refresh(task)
    return task


async def link_patient(
    db: AsyncSession, task_id: UUID, actor: User, patient_id: UUID | None
) -> HumanReviewTask:
    """F2: links the case and closes the item. The agent is not re-run."""
    task = await _open_item(db, task_id, actor, {TaskType.IDENTITY_REVIEW})
    if patient_id is None:
        await _audit(db, actor, task, "review.completed", note="None of these")
    else:
        if str(patient_id) not in (task.details or {}).get("candidates", []):
            raise HumanReviewInvalidChoiceError("Choose one of the offered patients")
        patient = await db.get(Patient, patient_id)
        intake = await db.get(IntakeCase, task.case_id)
        if patient is None or intake is None:
            raise HumanReviewInvalidChoiceError("That patient no longer exists")
        if intake.patient_id not in (None, patient.id):
            raise HumanReviewTaskWrongStateError("The case is already linked to another patient")
        intake.patient_id, intake.patient_name = patient.id, patient.name
        await _audit(db, actor, task, "review.patient_linked", patient_id=str(patient.id))
        # Staff confirmed who it is: a clinical message now joins a case (M4).
        await episode_service.attach_contact(db, intake, actor=actor)
    task.status = TaskStatus.COMPLETED
    await db.commit()
    await db.refresh(task)
    return task


async def reassign(
    db: AsyncSession, task_id: UUID, actor: User, doctor_id: UUID
) -> HumanReviewTask:
    """A held draft to a doctor: how the operator moves clinical text it may not approve."""
    if actor.role not in (UserRole.OPERATOR, UserRole.ADMIN):
        raise HumanReviewTaskWrongRoleError("Only the operator or the admin reassigns")
    task = await _open_item(db, task_id, actor, {TaskType.DRAFT_APPROVAL})
    doctor = await db.get(User, doctor_id)
    if doctor is None or doctor.role != UserRole.DOCTOR or not doctor.is_active:
        raise HumanReviewInvalidChoiceError("Choose an active doctor")
    task.target_role, task.assigned_to, task.status = UserRole.DOCTOR, doctor.id, TaskStatus.PENDING
    await _audit(db, actor, task, "review.reassigned", doctor_id=str(doctor.id))
    await db.commit()
    await db.refresh(task)
    return task


async def choose_case(
    db: AsyncSession, task_id: UUID, actor: User, episode_id: UUID | None
) -> HumanReviewTask:
    """ "Which case does this belong to?": one of the offered cases, or a new one."""
    task = await _open_item(db, task_id, actor, {TaskType.CASE_CHOICE})
    try:
        await episode_service.choose(db, task, episode_id, actor=actor)
    except episode_service.EpisodeClosedError as exc:
        raise HumanReviewTaskWrongStateError(str(exc)) from exc
    except episode_service.EpisodeError as exc:
        raise HumanReviewInvalidChoiceError(str(exc)) from exc
    await db.commit()
    await db.refresh(task)
    return task


async def answer_case_close(
    db: AsyncSession, task_id: UUID, actor: User, *, close: bool, note: str | None
) -> HumanReviewTask:
    """ "Close this case?": Close (with the outcome note) or Keep open, which
    asks again after case_close_nudge_days of quiet."""
    task = await _open_item(db, task_id, actor, {TaskType.CASE_CLOSE})
    episode = await db.get(Episode, task.episode_id) if task.episode_id else None
    if episode is None:
        raise HumanReviewTaskWrongStateError("The case is gone")
    if close:
        try:
            await episode_service.close(db, episode, note=note or "", actor=actor)
        except episode_service.EpisodeClosedError as exc:
            raise HumanReviewTaskWrongStateError(str(exc)) from exc
        except episode_service.EpisodeError as exc:
            raise HumanReviewInvalidChoiceError(str(exc)) from exc
    else:
        until = datetime.now(UTC) + timedelta(days=settings.case_close_nudge_days)
        episode.nudge_snoozed_until = until
        task.status = TaskStatus.COMPLETED
        await record_event(
            db,
            actor=actor,
            action="case.kept_open",
            details={"episode_id": str(episode.id), "until": until.isoformat(), "note": note},
        )
        await _audit(db, actor, task, "review.completed", note="Kept open")
    await db.commit()
    await db.refresh(task)
    return task
