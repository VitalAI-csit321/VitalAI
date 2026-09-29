import json
from dataclasses import replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import get_llm
from app.models.call import Call, CallStatus
from app.models.case import IntakeCase
from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User
from app.schemas.call import (
    CallCreate,
    CallEscalateRequest,
    CallRouteRequest,
    CallRoutingOverride,
)
from app.services import identity_service, onboarding_service
from app.services.audit_service import record_event
from app.services.content_classifier import classify_content
from app.services.identity_service import ONBOARDING_INTENTS
from app.services.task_routing_gate import (
    TaskRoutingGateResult,
    TaskRoutingOutcome,
    evaluate_task_routing_gate,
)
from app.services.task_routing_rules import resolve_target_role


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


def _priority_for_gate(gate: TaskRoutingGateResult) -> TaskPriority:
    if gate.outcome == TaskRoutingOutcome.HUMAN_REVIEW:
        return TaskPriority.URGENT if gate.override_reason else TaskPriority.HIGH
    if gate.outcome == TaskRoutingOutcome.AUTO_ROUTED_FLAGGED:
        return TaskPriority.MEDIUM
    return TaskPriority.LOW


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


async def _get_or_create_call_task(db: AsyncSession, call: Call) -> Task:
    result = await db.execute(select(Task).where(Task.call_id == call.id))
    task = result.scalars().first()
    if task is None:
        task = Task(
            case_id=call.case_id,
            call_id=call.id,
            source=TaskSource.CALL,
            status=TaskItemStatus.PENDING,
        )
        db.add(task)
    return task


async def route_call(
    db: AsyncSession, call_id: UUID, payload: CallRouteRequest, actor: User
) -> tuple[Call, Task, TaskRoutingGateResult]:
    call = await db.get(Call, call_id)
    if call is None:
        raise CallNotFoundError("Call not found")
    if not call.transcript or not call.transcript.strip():
        raise TranscriptRequiredError("A transcript is required before urgency routing")

    llm = get_llm()
    category, confidence = await classify_content(
        db, llm, call.transcript, actor=actor, channel="call"
    )
    target_role = resolve_target_role(category)
    gate = evaluate_task_routing_gate(category, confidence, call.transcript)
    priority = _priority_for_gate(gate)

    call.category = category
    call.confidence = confidence
    call.target_role = target_role
    call.status = CallStatus.PROCESSED

    task = await _get_or_create_call_task(db, call)
    task.category = category
    task.target_role = target_role
    task.priority = priority
    await db.flush()

    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="call.routed",
        details={
            "call_id": str(call.id),
            "task_id": str(task.id),
            "category": category.value,
            "confidence": confidence,
            "target_role": target_role.value,
            "outcome": gate.outcome.value,
            "override_reason": gate.override_reason,
        },
    )
    await db.commit()
    if settings.email_booking_conversation_enabled and category in ONBOARDING_INTENTS:
        await _profile_from_call(db, call, task, llm, actor)
    await db.refresh(call)
    await db.refresh(task)
    return call, task, gate


_CALLER_NOT_IDENTIFIED = (
    "No provisional profile was created from this call: the transcript gave no name, or "
    "the details match an existing patient only partly. Confirm who called before booking."
)


async def _profile_from_call(db: AsyncSession, call: Call, task: Task, llm, actor: User) -> None:
    """A caller asking to book or register: their phone number (caller ID)
    plus a name from the transcript is enough for a provisional profile, the
    call-side twin of an email's sender address plus name. An existing
    patient is matched only by the usual full rule (name + DOB + contact)."""
    case = await db.get(IntakeCase, call.case_id)
    if case is None or case.patient_id is not None:
        return
    fields = await identity_service.extract_identity_fields(
        db, llm, call.transcript or "", actor=actor
    )
    fields = replace(fields, phone=call.phone_number)
    result = await identity_service.resolve_patient(db, sender=None, fields=fields)
    created = False
    if result.outcome == identity_service.IdentityOutcome.MATCHED and result.patient is not None:
        case.patient_id = result.patient.id
        case.patient_name = result.patient.name
    elif result.outcome == identity_service.IdentityOutcome.NO_MATCH and fields.name:
        created = (
            await onboarding_service.start_onboarding(
                db, case_id=case.id, sender=None, fields=fields, actor=actor
            )
            is not None
        )
    else:
        task.handover_context = _CALLER_NOT_IDENTIFIED
    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="call.identity_resolved",
        details={
            "call_id": str(call.id),
            "outcome": result.outcome.value,
            # Field names only, as identity_service records them.
            "fields_present": fields.present(),
            "provisional_created": created,
        },
    )
    await db.commit()


async def override_call_routing(
    db: AsyncSession, call_id: UUID, payload: CallRoutingOverride, actor: User
) -> tuple[Call, Task]:
    call = await db.get(Call, call_id)
    if call is None:
        raise CallNotFoundError("Call not found")
    if not call.transcript or not call.transcript.strip():
        raise TranscriptRequiredError("A transcript is required before urgency routing")

    result = await db.execute(select(Task).where(Task.call_id == call.id))
    task = result.scalars().first()
    if task is None:
        raise CallNotRoutedError("Call must be routed before its routing can be overridden")

    previous_category = call.category.value if call.category else None
    new_target_role = resolve_target_role(payload.category)

    call.category = payload.category
    call.confidence = 1.0  # a human override is certain by definition
    call.target_role = new_target_role
    call.routing_overridden = True
    task.category = payload.category
    task.target_role = new_target_role
    await db.flush()

    await record_event(
        db,
        case_id=call.case_id,
        actor=actor,
        action="call.routing_overridden",
        details={
            "call_id": str(call.id),
            "previous_category": previous_category,
            "new_category": payload.category.value,
            "new_target_role": new_target_role.value,
            "reason": payload.reason,
        },
    )
    await db.commit()
    await db.refresh(call)
    await db.refresh(task)
    return call, task


async def escalate_call(
    db: AsyncSession, call_id: UUID, payload: CallEscalateRequest, actor: User
) -> tuple[Call, Task, dict]:
    call = await db.get(Call, call_id)
    if call is None:
        raise CallNotFoundError("Call not found")
    if not call.transcript or not call.transcript.strip():
        raise TranscriptRequiredError("A transcript is required before escalation")
    if call.category is None or call.target_role is None:
        raise CallNotRoutedError("Call must be routed before escalation")

    if payload.assigned_to is not None and await db.get(User, payload.assigned_to) is None:
        raise AssigneeNotFoundError(f"User {payload.assigned_to} not found")

    result = await db.execute(select(Task).where(Task.call_id == call.id))
    task = result.scalars().first()
    if task is None:
        raise CallNotRoutedError("Call must be routed before escalation")
    if task.status == TaskItemStatus.ESCALATED:
        raise DuplicateEscalationError("An active escalation task already exists for this call")

    context = {
        "call_id": str(call.id),
        "case_id": str(call.case_id),
        "phone_number": call.phone_number,
        "transcript": call.transcript,
        "category": call.category.value,
        "target_role": call.target_role.value,
        "override_applied": call.routing_overridden,
        "escalation_reason": payload.reason,
    }

    task.status = TaskItemStatus.ESCALATED
    task.priority = TaskPriority.URGENT
    if payload.assigned_to is not None:
        task.assigned_to = payload.assigned_to
    task.handover_context = json.dumps(context)
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
            "priority": task.priority.value,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
            "full_context_attached": True,
        },
    )
    await db.commit()
    await db.refresh(call)
    await db.refresh(task)
    return call, task, context
