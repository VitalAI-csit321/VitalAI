import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Call, CallStatus
from app.models.case import IntakeCase
from app.models.routing import RoutingDecision
from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource
from app.models.triage import TriageCategory, TriageResult
from app.models.user import User
from app.schemas.call import (
    CallCreate,
    CallEscalateRequest,
    CallRouteRequest,
    CallRoutingOverride,
)
from app.schemas.triage import TriageRequest
from app.services import routing_service, triage_service
from app.services.audit_service import record_event
from app.services.routing_rules import decide


class CaseNotFoundError(Exception):
    """Raised when a call references an intake case that does not exist."""


class CallNotFoundError(Exception):
    """Raised when a requested call does not exist."""


class TranscriptRequiredError(Exception):
    """Raised when routing/escalation needs a transcript but none is present."""


class CallNotRoutedError(Exception):
    """Raised when escalation is requested before the call has been routed."""


class DuplicateEscalationError(Exception):
    """Raised when an active escalation task already exists for the call."""


class AssigneeNotFoundError(Exception):
    """Raised when the requested assignee does not exist."""


def _priority_for_category(category: TriageCategory) -> TaskPriority:
    if category == TriageCategory.IMMEDIATE:
        return TaskPriority.URGENT
    if category in (TriageCategory.TIME_SENSITIVE, TriageCategory.LOW_CONFIDENCE):
        return TaskPriority.HIGH
    return TaskPriority.MEDIUM


async def create_call(db: AsyncSession, payload: CallCreate, actor: User) -> Call:
    case = await db.get(IntakeCase, payload.case_id)
    if case is None:
        raise CaseNotFoundError(f"Case {payload.case_id} not found")

    call = Call(
        case_id=payload.case_id,
        phone_number=payload.phone_number,
        transcript=payload.transcript,
        status=CallStatus.RECEIVED,
    )
    db.add(call)
    await db.flush()

    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="call.created",
        details={"call_id": str(call.id), "manual_entry": True},
    )
    await db.commit()
    await db.refresh(call)
    return call


async def get_call(db: AsyncSession, call_id: UUID) -> Call | None:
    return await db.get(Call, call_id)


async def list_calls(db: AsyncSession) -> list[Call]:
    result = await db.execute(select(Call).order_by(Call.created_at.desc()))
    return list(result.scalars().all())


async def route_call(
    db: AsyncSession,
    call_id: UUID,
    payload: CallRouteRequest,
    actor: User,
) -> tuple[Call, TriageResult, RoutingDecision]:
    call = await db.get(Call, call_id)
    if call is None:
        raise CallNotFoundError("Call not found")
    if not call.transcript or not call.transcript.strip():
        raise TranscriptRequiredError("A transcript is required before urgency routing")

    triage_response = await triage_service.classify(
        db,
        TriageRequest(
            case_id=call.case_id,
            contact_reason=call.transcript,
            keywords=payload.keywords,
            patient_priority_flags=payload.patient_priority_flags,
        ),
        actor,
    )
    decision = await routing_service.route_from_triage_id(db, triage_response.triage_id, actor)
    if decision is None:  # defensive: the triage row was just created
        raise RuntimeError("Routing decision could not be created")

    triage = await db.get(TriageResult, triage_response.triage_id)
    if triage is None:
        raise RuntimeError("Triage result could not be reloaded")

    call.triage_id = triage.id
    call.routing_id = decision.id
    call.urgency_tier = triage.category
    call.target_queue = decision.target_queue
    call.routing_overridden = False
    call.status = CallStatus.PROCESSED

    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="call.routed",
        details={
            "call_id": str(call.id),
            "triage_id": str(triage.id),
            "routing_id": str(decision.id),
            "urgency_tier": triage.category.value,
            "target_queue": decision.target_queue,
            "escalated": decision.escalated,
        },
    )
    await db.commit()
    await db.refresh(call)
    return call, triage, decision


async def override_call_routing(
    db: AsyncSession,
    call_id: UUID,
    payload: CallRoutingOverride,
    actor: User,
) -> tuple[Call, TriageResult, RoutingDecision]:
    call = await db.get(Call, call_id)
    if call is None:
        raise CallNotFoundError("Call not found")
    if not call.transcript or not call.transcript.strip():
        raise TranscriptRequiredError("A transcript is required before urgency routing")

    previous_category = call.urgency_tier.value if call.urgency_tier else None
    previous_queue = call.target_queue
    action, target_queue, escalated = decide(payload.category)

    triage = TriageResult(
        case_id=call.case_id,
        category=payload.category,
        confidence=1.0,
        rationale=f"Human override: {payload.reason}",
        routed=True,
    )
    db.add(triage)
    await db.flush()

    decision = RoutingDecision(
        case_id=call.case_id,
        triage_id=triage.id,
        action=action,
        target_queue=target_queue,
        escalated=escalated,
    )
    db.add(decision)
    await db.flush()

    call.triage_id = triage.id
    call.routing_id = decision.id
    call.urgency_tier = payload.category
    call.target_queue = target_queue
    call.routing_overridden = True
    call.status = CallStatus.PROCESSED

    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="call.routing_overridden",
        details={
            "call_id": str(call.id),
            "previous_category": previous_category,
            "new_category": payload.category.value,
            "previous_queue": previous_queue,
            "new_queue": target_queue,
            "reason": payload.reason,
            "triage_id": str(triage.id),
            "routing_id": str(decision.id),
        },
    )
    await db.commit()
    await db.refresh(call)
    return call, triage, decision


async def escalate_call(
    db: AsyncSession,
    call_id: UUID,
    payload: CallEscalateRequest,
    actor: User,
) -> tuple[Call, Task, dict]:
    call = await db.get(Call, call_id)
    if call is None:
        raise CallNotFoundError("Call not found")
    if not call.transcript or not call.transcript.strip():
        raise TranscriptRequiredError("A transcript is required before escalation")
    if call.routing_id is None or call.urgency_tier is None or call.target_queue is None:
        raise CallNotRoutedError("Call must be routed before escalation")

    if payload.assigned_to is not None and await db.get(User, payload.assigned_to) is None:
        raise AssigneeNotFoundError(f"User {payload.assigned_to} not found")

    active = await db.execute(
        select(Task).where(
            Task.call_id == call.id,
            Task.status.in_(
                [TaskItemStatus.PENDING, TaskItemStatus.IN_PROGRESS, TaskItemStatus.ESCALATED]
            ),
        )
    )
    if active.scalars().first() is not None:
        raise DuplicateEscalationError("An active escalation task already exists for this call")

    triage = await db.get(TriageResult, call.triage_id) if call.triage_id else None
    decision = await db.get(RoutingDecision, call.routing_id)
    context = {
        "call_id": str(call.id),
        "case_id": str(call.case_id),
        "phone_number": call.phone_number,
        "transcript": call.transcript,
        "urgency_tier": call.urgency_tier.value,
        "target_queue": call.target_queue,
        "routing_action": decision.action.value if decision else None,
        "routing_rationale": triage.rationale if triage else None,
        "override_applied": call.routing_overridden,
        "escalation_reason": payload.reason,
    }

    task = Task(
        case_id=call.case_id,
        call_id=call.id,
        assigned_to=payload.assigned_to,
        source=TaskSource.CALL,
        priority=_priority_for_category(call.urgency_tier),
        status=TaskItemStatus.ESCALATED,
        target_queue=call.target_queue,
        handover_context=json.dumps(context),
    )
    db.add(task)
    call.status = CallStatus.ESCALATED
    await db.flush()

    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="call.escalated",
        details={
            "call_id": str(call.id),
            "task_id": str(task.id),
            "target_queue": task.target_queue,
            "priority": task.priority.value,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
            "full_context_attached": True,
        },
    )
    await db.commit()
    await db.refresh(call)
    await db.refresh(task)
    return call, task, context
