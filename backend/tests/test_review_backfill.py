"""Messages already waiting when the Review Queue shipped get the item a new
message would get, exactly once, and nothing else does."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskSource
from app.models.user import UserRole
from app.services import (
    booking_service,
    identity_service,
    prescription_service,
    review_backfill,
)
from app.services.identity_service import IdentityOutcome
from tests.review_helpers import assign, inbox_task


async def _items(db, task: Task) -> list[HumanReviewTask]:
    result = await db.execute(
        select(HumanReviewTask).where(HumanReviewTask.inbox_task_id == task.id)
    )
    return list(result.scalars().all())


async def _legacy_draft(db, task: Task) -> ApprovalRequest:
    """A draft held for approval before migration 0037: no review item."""
    approval = ApprovalRequest(
        action_type="email.draft_reply",
        case_id=task.case_id,
        payload={"task_id": str(task.id), "draft": "Hi, your script is ready."},
        status=ApprovalStatus.PENDING,
    )
    db.add(approval)
    await db.flush()
    task.draft_approval_id = approval.id
    await db.commit()
    return approval


async def _held(db, reason: str, **task_kw) -> Task:
    task = await inbox_task(db, **task_kw)
    task.handover_context = reason
    await db.commit()
    return task


async def test_a_waiting_draft_gets_one_item_for_the_patients_doctor(
    db_session, patient, doctor_user
):
    await assign(db_session, doctor_user, patient)
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    approval = await _legacy_draft(db_session, task)

    assert await review_backfill.backfill(db_session, actor=None) == 1
    (item,) = await _items(db_session, task)
    assert item.task_type == TaskType.DRAFT_APPROVAL
    assert (item.target_role, item.assigned_to) == (UserRole.DOCTOR, doctor_user.id)
    assert item.approval_id == approval.id

    assert await review_backfill.backfill(db_session, actor=None) == 0
    assert len(await _items(db_session, task)) == 1


async def test_an_identity_hold_goes_to_front_desk(db_session):
    reason = identity_service._HOLD_REASONS[IdentityOutcome.AMBIGUOUS]
    task = await _held(db_session, reason)
    await review_backfill.backfill(db_session, actor=None)
    (item,) = await _items(db_session, task)
    assert (item.task_type, item.target_role) == (TaskType.IDENTITY_REVIEW, UserRole.FRONT_DESK)


async def test_a_known_handover_goes_to_the_messages_owner(db_session, patient, doctor_user):
    await assign(db_session, doctor_user, patient)
    task = await _held(
        db_session,
        booking_service.NO_SLOTS_REASON,
        category=TaskCategory.APPOINTMENT_REQUEST,
        patient=patient,
    )
    no_doctor = await _held(db_session, booking_service.NO_DOCTOR_REASON)
    await review_backfill.backfill(db_session, actor=None)
    (item,) = await _items(db_session, task)
    assert item.task_type == TaskType.AGENT_HANDOVER
    assert item.notes == booking_service.NO_SLOTS_REASON
    (operator_item,) = await _items(db_session, no_doctor)
    assert operator_item.target_role == UserRole.OPERATOR


async def test_a_waiting_prescription_request_goes_to_its_prescriber(db_session, doctor_user):
    task = await _held(
        db_session,
        prescription_service.REVIEW_DUE_REASON,
        category=TaskCategory.PRESCRIPTION_RENEWAL,
    )
    task.target_role = UserRole.DOCTOR
    task.assigned_to = doctor_user.id
    await db_session.commit()
    await review_backfill.backfill(db_session, actor=None)
    (item,) = await _items(db_session, task)
    assert (item.task_type, item.assigned_to) == (TaskType.PRESCRIPTION_REQUEST, doctor_user.id)


async def test_an_agent_failure_goes_to_the_operator(db_session):
    task = await _held(
        db_session, "Automated handling stopped at retrieval (TimeoutError). Needs a manual reply."
    )
    await review_backfill.backfill(db_session, actor=None)
    (item,) = await _items(db_session, task)
    assert (item.task_type, item.target_role) == (TaskType.AGENT_FAILURE, UserRole.OPERATOR)


async def test_what_a_new_message_would_not_get_is_left_alone(db_session):
    no_reply = await _held(db_session, "Automated notification with no request to respond to.")
    deleted = await inbox_task(db_session)
    await _legacy_draft(db_session, deleted)
    deleted.deleted_at = datetime.now(UTC)
    voicemail = await _held(db_session, "Call back +61400000000.")
    voicemail.source = TaskSource.CALL
    done = await inbox_task(db_session)
    await _legacy_draft(db_session, done)
    done.status = TaskItemStatus.COMPLETED
    handled = await inbox_task(db_session)
    approval = await _legacy_draft(db_session, handled)
    db_session.add(
        HumanReviewTask(
            case_id=handled.case_id,
            inbox_task_id=handled.id,
            task_type=TaskType.DRAFT_APPROVAL,
            target_role=UserRole.FRONT_DESK,
            status=TaskStatus.COMPLETED,
            approval_id=approval.id,
        )
    )
    await db_session.commit()

    assert await review_backfill.backfill(db_session, actor=None) == 0
    for task in (no_reply, deleted, voicemail, done):
        assert await _items(db_session, task) == []
    assert len(await _items(db_session, handled)) == 1
