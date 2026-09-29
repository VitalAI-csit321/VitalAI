from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.approval import ApprovalRequest
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.human_review import TaskPriority as ReviewPriority
from app.models.task import TaskCategory, TaskPriority
from app.models.user import UserRole
from app.services import approval_service, email_service, review_routing
from app.services.reply_gate import ReplyGateResult, ReplyWorthiness
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
from tests.agent_fakes import seed_email
from tests.review_helpers import assign, events, inbox_task
from tests.test_agent_approval_interrupt import _paused, fake_llm  # noqa: F401


def _item(task, status=TaskStatus.PENDING) -> HumanReviewTask:
    return HumanReviewTask(
        case_id=task.case_id,
        inbox_task_id=task.id,
        task_type=TaskType.ROUTING_REVIEW,
        target_role=UserRole.OPERATOR,
        status=status,
    )


async def test_one_open_item_per_message_and_kind(db_session):
    task = await inbox_task(db_session)
    first = _item(task)
    db_session.add(first)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_item(task))

    first.status = TaskStatus.COMPLETED
    await db_session.commit()
    db_session.add(_item(task))
    await db_session.commit()  # a closed item no longer blocks a new one


async def test_held_draft_follows_the_message_queue(db_session):
    task = await inbox_task(db_session)  # general_administrative -> front desk
    item = await review_routing.open_item(
        db_session, kind=TaskType.DRAFT_APPROVAL, inbox_task=task, reason="r", actor=None
    )
    assert (item.target_role, item.assigned_to) == (UserRole.FRONT_DESK, None)
    assert item.inbox_task_id == task.id and item.case_id == task.case_id
    (event,) = await events(db_session, "review.opened")
    assert event.details["review_id"] == str(item.id)
    assert event.details["kind"] == "draft_approval"


async def test_doctor_work_goes_to_the_patients_doctor(db_session, patient, doctor_user):
    await assign(db_session, doctor_user, patient)
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    item = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_HANDOVER, inbox_task=task, reason="r", actor=None
    )
    assert (item.target_role, item.assigned_to) == (UserRole.DOCTOR, doctor_user.id)


async def test_doctor_work_without_a_doctor_goes_to_the_operator(db_session, patient):
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    item = await review_routing.open_item(
        db_session, kind=TaskType.DRAFT_APPROVAL, inbox_task=task, reason="r", actor=None
    )
    assert (item.target_role, item.assigned_to) == (UserRole.OPERATOR, None)


@pytest.mark.parametrize(
    ("kind", "role"),
    [
        (TaskType.IDENTITY_REVIEW, UserRole.FRONT_DESK),
        (TaskType.ROUTING_REVIEW, UserRole.OPERATOR),
        (TaskType.INTENT_REVIEW, UserRole.OPERATOR),
        (TaskType.AGENT_FAILURE, UserRole.OPERATOR),
        (TaskType.COMPLAINT_REVIEW, UserRole.OPERATOR),
    ],
)
async def test_fixed_owners(db_session, kind, role):
    task = await inbox_task(db_session, category=TaskCategory.APPOINTMENT_REQUEST)
    item = await review_routing.open_item(
        db_session, kind=kind, inbox_task=task, reason="r", actor=None
    )
    assert item.target_role == role


async def test_owner_override(db_session):
    task = await inbox_task(db_session, category=TaskCategory.APPOINTMENT_REQUEST)
    item = await review_routing.open_item(
        db_session,
        kind=TaskType.AGENT_HANDOVER,
        inbox_task=task,
        reason="r",
        actor=None,
        owner=UserRole.OPERATOR,
    )
    assert item.target_role == UserRole.OPERATOR


async def test_urgent_message_gives_a_high_priority_item(db_session):
    task = await inbox_task(db_session, priority=TaskPriority.URGENT)
    item = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_FAILURE, inbox_task=task, reason="r", actor=None
    )
    assert item.priority == ReviewPriority.HIGH


async def test_a_rerun_gets_the_open_item_back(db_session):
    task = await inbox_task(db_session)
    first = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_HANDOVER, inbox_task=task, reason="r", actor=None
    )
    again = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_HANDOVER, inbox_task=task, reason="r", actor=None
    )
    assert again.id == first.id
    assert len(await events(db_session, "review.opened")) == 1


# --- Task 3: held drafts link to their approval (D1, D2) ---------------------


async def _items(db, **where) -> list[HumanReviewTask]:
    query = select(HumanReviewTask)
    for key, value in where.items():
        query = query.where(getattr(HumanReviewTask, key) == value)
    return list((await db.execute(query)).scalars().all())


async def _draft(db, task, **payload):
    return await approval_service.create_approval_request(
        db,
        action_type="email.draft_reply",
        payload={"task_id": str(task.id), "draft": "Hi", **payload},
        case_id=task.case_id,
    )


async def test_held_draft_opens_one_linked_item(db_session):
    task = await inbox_task(db_session)
    approval = await _draft(db_session, task, critic_reason="mentions a price")
    (item,) = await _items(db_session, inbox_task_id=task.id)
    assert item.task_type == TaskType.DRAFT_APPROVAL
    assert item.approval_id == approval.id
    assert "mentions a price" in item.notes


async def test_other_approvals_open_no_item(db_session):
    task = await inbox_task(db_session)
    await approval_service.create_approval_request(
        db_session, action_type="patient.assignment.suggested", payload={"task_id": str(task.id)}
    )
    assert await _items(db_session, inbox_task_id=task.id) == []


async def test_approve_completes_and_reject_cancels_the_item(db_session, operator_user):
    for decide, status, action in (
        (approval_service.approve, TaskStatus.COMPLETED, "review.completed"),
        (approval_service.reject, TaskStatus.CANCELLED, "review.dismissed"),
    ):
        task = await inbox_task(db_session)
        approval = await _draft(db_session, task)
        await decide(db_session, approval.id, operator_user)
        (item,) = await _items(db_session, inbox_task_id=task.id)
        assert item.status == status
        assert any(e.details["review_id"] == str(item.id) for e in await events(db_session, action))


async def test_flag_off_held_draft_has_one_item(db_session, operator_user, monkeypatch):
    monkeypatch.setattr(settings, "email_auto_send_enabled", False)
    monkeypatch.setattr(
        email_service,
        "check_reply_worthiness",
        AsyncMock(return_value=ReplyGateResult(verdict=ReplyWorthiness.WORTHY, reason="ok")),
    )
    monkeypatch.setattr(email_service, "generate_draft", AsyncMock(return_value=("Hello", True)))
    monkeypatch.setattr(email_service, "check_output", AsyncMock(return_value=None))
    email, task = await seed_email(db_session)
    gate = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)
    outcome = await email_service.draft_reply(db_session, task, email, operator_user, gate, 0.95)
    (item,) = await _items(db_session, inbox_task_id=task.id)
    assert str(item.approval_id) == outcome.approval_id


async def test_graph_held_draft_has_one_item_across_resume(
    detached_sessionmaker,
    db_session,
    admin_user,
    fake_llm,  # noqa: F811
):
    from langgraph.types import Command

    from app.agents.graph import run_config

    graph, ctx, tid, _ = await _paused(detached_sessionmaker, db_session)
    (row,) = (
        (
            await db_session.execute(
                select(ApprovalRequest).where(ApprovalRequest.external_ref == tid)
            )
        )
        .scalars()
        .all()
    )
    (item,) = await _items(db_session, approval_id=row.id)
    await approval_service.approve(db_session, row.id, admin_user)
    await graph.ainvoke(Command(resume={"approved": True}), run_config(tid), context=ctx)
    assert [i.id for i in await _items(db_session, approval_id=row.id)] == [item.id]
    await db_session.refresh(item)
    assert item.status == TaskStatus.COMPLETED


async def test_second_decision_from_the_other_screen_is_refused(db_session, operator_user):
    task = await inbox_task(db_session)
    approval = await _draft(db_session, task)
    await approval_service.approve(db_session, approval.id, operator_user)
    with pytest.raises(approval_service.ApprovalAlreadyDecidedError):
        await approval_service.reject(db_session, approval.id, operator_user)
    (item,) = await _items(db_session, inbox_task_id=task.id)
    assert item.status == TaskStatus.COMPLETED
