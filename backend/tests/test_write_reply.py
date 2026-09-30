"""Write reply (review queue spec D14, test 1c): staff send their own answer to
an email when no AI draft is waiting on approval."""

from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.models.approval import ApprovalStatus
from app.models.call import Call
from app.models.email import Email
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskSource
from app.services import approval_service, email_service, prescription_service, review_routing
from tests.review_helpers import assign, events, inbox_task
from tests.test_inbox import _held


async def _listed(client, headers, task):
    (message,) = [
        m
        for m in (await client.get("/api/v1/inbox", headers=headers)).json()["items"]
        if m["id"] == str(task.id)
    ]
    return message


async def _reply(client, headers, task, text="Thanks, we open at 9."):
    return await client.post(f"/api/v1/inbox/{task.id}/reply", json={"text": text}, headers=headers)


async def _no_draft(db, client, headers):
    return await inbox_task(db)


async def _blocked(db, client, headers):
    task = await inbox_task(db)
    task.handover_context = "The draft was blocked by the content guardrail."
    await db.commit()
    return task


async def _rejected(db, client, headers):
    task = await _held(db, TaskCategory.GENERAL_ADMINISTRATIVE)
    response = await client.post(
        f"/api/v1/approvals/{task.draft_approval_id}/reject",
        json={"notes": "wrong hours"},
        headers=headers,
    )
    assert response.status_code == 200
    return task


@pytest.mark.parametrize("setup", [_no_draft, _blocked, _rejected])
async def test_available_and_sends_once(db_session, client, front_desk_headers, setup):
    task = await setup(db_session, client, front_desk_headers)
    assert (await _listed(client, front_desk_headers, task))["canWriteReply"] is True

    response = await _reply(client, front_desk_headers, task, "  Thanks, we open at 9.  ")
    assert response.status_code == 200
    body = response.json()
    assert (body["draftSent"], body["draftText"], body["canWriteReply"]) == (
        True,
        "Thanks, we open at 9.",
        False,
    )

    (sent,) = await events(db_session, "email.sent")
    assert sent.details["manual"] is True
    assert sent.details["approval_id"] is None
    await db_session.refresh(task)
    assert (task.draft_sent, task.draft_text) == (True, "Thanks, we open at 9.")


async def test_refused_while_a_draft_awaits_approval(db_session, client, front_desk_headers):
    task = await _held(db_session, TaskCategory.GENERAL_ADMINISTRATIVE)
    assert (await _listed(client, front_desk_headers, task))["canWriteReply"] is False
    assert (await _reply(client, front_desk_headers, task)).status_code == 409
    assert await events(db_session, "email.sent") == []


async def test_offered_once_the_draft_is_rejected(db_session, client, front_desk_headers):
    task = await _held(db_session, TaskCategory.GENERAL_ADMINISTRATIVE)
    assert (await _listed(client, front_desk_headers, task))["canWriteReply"] is False
    await client.post(
        f"/api/v1/approvals/{task.draft_approval_id}/reject", json={}, headers=front_desk_headers
    )
    assert (await _listed(client, front_desk_headers, task))["canWriteReply"] is True


async def test_offered_when_an_approved_draft_was_never_delivered(
    db_session, client, front_desk_headers
):
    # The approve went through but the send failed: draft_sent stays False and
    # re-approving is refused, so the reply is written by hand.
    task = await _held(db_session, TaskCategory.GENERAL_ADMINISTRATIVE)
    approval = await approval_service.get_approval(db_session, task.draft_approval_id)
    approval.status = ApprovalStatus.APPROVED
    await db_session.commit()
    assert (await _listed(client, front_desk_headers, task))["canWriteReply"] is True


async def test_second_send_is_refused_and_sends_nothing(db_session, client, front_desk_headers):
    task = await inbox_task(db_session)
    assert (await _reply(client, front_desk_headers, task)).status_code == 200
    assert (await _reply(client, front_desk_headers, task, "Again")).status_code == 409
    assert len(await events(db_session, "email.sent")) == 1
    await db_session.refresh(task)
    assert task.draft_text == "Thanks, we open at 9."


async def test_refused_on_a_call(db_session, client, admin_headers):
    task = await inbox_task(db_session)
    call = Call(case_id=task.case_id, phone_number="+61400000000")
    db_session.add(call)
    await db_session.flush()
    task.source, task.call_id = TaskSource.CALL, call.id
    await db_session.commit()
    assert (await _reply(client, admin_headers, task)).status_code == 409
    assert await events(db_session, "email.sent") == []


@pytest.mark.parametrize(
    "reason", [prescription_service.REVIEW_DUE_REASON, prescription_service.TO_CONSIDER_REASON]
)
async def test_refused_on_the_prescribers_request(db_session, client, admin_headers, reason):
    """The request shares the patient's email; the answer to the patient is the
    acknowledgement on their own message, so a second reply is never offered."""
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL)
    task.handover_context = reason
    await db_session.commit()
    assert (await _listed(client, admin_headers, task))["canWriteReply"] is False
    assert (await _reply(client, admin_headers, task)).status_code == 409
    assert await events(db_session, "email.sent") == []


async def test_operator_writes_on_a_front_desk_message(db_session, client, operator_headers):
    task = await inbox_task(db_session)  # front desk's
    # The operator reaches a front desk message through its review item (D6).
    item = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_HANDOVER, inbox_task=task, reason="why", actor=None
    )
    await db_session.commit()
    assert (await _reply(client, operator_headers, task)).status_code == 200
    await db_session.refresh(item)
    assert item.status == TaskStatus.COMPLETED


async def test_operator_may_not_answer_a_doctors_patient(
    db_session, client, operator_headers, doctor_user, patient
):
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    await assign(db_session, doctor_user, patient)
    # An agent failure is the operator's item, so the message opens for it...
    item = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_FAILURE, inbox_task=task, reason="why", actor=None
    )
    await db_session.commit()
    opened = await client.get(f"/api/v1/inbox/{task.id}", headers=operator_headers)
    assert opened.status_code == 200
    assert opened.json()["canWriteReply"] is False
    # ...but the reply is the doctor's to write.
    assert (await _reply(client, operator_headers, task)).status_code == 403
    assert await events(db_session, "email.sent") == []
    await db_session.refresh(item)
    assert item.status == TaskStatus.PENDING
    assert any(
        e.details.get("task_id") == str(task.id)
        for e in await events(db_session, "governance.access_denied")
    )


async def test_a_message_the_actor_cannot_open_is_not_found(db_session, client, doctor_headers):
    task = await inbox_task(db_session)
    assert (await _reply(client, doctor_headers, task)).status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 10_001])
async def test_empty_or_oversized_text_is_refused(db_session, client, front_desk_headers, text):
    task = await inbox_task(db_session)
    assert (await _reply(client, front_desk_headers, task, text)).status_code == 422


@pytest.mark.parametrize("kind", [TaskType.AGENT_FAILURE, TaskType.COMPLAINT_REVIEW])
async def test_sending_completes_the_linked_item(db_session, client, admin_headers, kind):
    task = await inbox_task(db_session)
    item = await review_routing.open_item(
        db_session, kind=kind, inbox_task=task, reason="why", actor=None
    )
    # Not every kind is answered by a reply: a routing question stays open.
    routing = await review_routing.open_item(
        db_session, kind=TaskType.ROUTING_REVIEW, inbox_task=task, reason="why", actor=None
    )
    await db_session.commit()
    assert (await _reply(client, admin_headers, task)).status_code == 200

    await db_session.refresh(item)
    await db_session.refresh(routing)
    assert (item.status, routing.status) == (TaskStatus.COMPLETED, TaskStatus.PENDING)
    (done,) = [
        e
        for e in await events(db_session, "review.completed")
        if e.details["review_id"] == str(item.id)
    ]
    assert (done.details["kind"], done.details["note"]) == (kind.value, "Replied by hand")


async def test_not_offered_on_an_archived_message(db_session, client, front_desk_headers):
    task = await inbox_task(db_session)
    task.status = TaskItemStatus.COMPLETED
    await db_session.commit()
    archived = await client.get(
        "/api/v1/inbox", params={"archived": "true"}, headers=front_desk_headers
    )
    (message,) = [m for m in archived.json()["items"] if m["id"] == str(task.id)]
    assert message["canWriteReply"] is False
    assert (await _reply(client, front_desk_headers, task)).status_code == 409


async def test_a_failed_send_changes_nothing(db_session, client, admin_headers, monkeypatch):
    task = await inbox_task(db_session)
    email = (
        await db_session.execute(select(Email).where(Email.case_id == task.case_id))
    ).scalar_one()
    email.external_id = "AAMk-manual"
    item = await review_routing.open_item(
        db_session, kind=TaskType.AGENT_FAILURE, inbox_task=task, reason="why", actor=None
    )
    await db_session.commit()
    monkeypatch.setattr(email_service.settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    monkeypatch.setattr(
        "app.services.outlook_client.send_reply",
        AsyncMock(side_effect=httpx.ConnectError("mail server down")),
    )

    assert (await _reply(client, admin_headers, task)).status_code == 502
    await db_session.refresh(item)
    await db_session.refresh(task)
    assert (item.status, task.draft_sent) == (TaskStatus.PENDING, False)
    assert await events(db_session, "email.sent") == []
    assert await events(db_session, "review.completed") == []


# The AI draft is generated in the background after ingest commits the Task,
# so a person can answer by hand before the pipeline finishes. What the
# pipeline does next must not send a second email or re-offer approval.


async def test_a_late_ai_draft_does_not_undo_a_manual_reply(db_session, client, front_desk_headers):
    task = await inbox_task(db_session)
    assert (await _reply(client, front_desk_headers, task)).status_code == 200

    # The graph's create_approval node: an approval, then persist_draft.
    approval = await approval_service.create_approval_request(
        db_session,
        action_type="email.draft_reply",
        payload={"task_id": str(task.id), "draft": "AI text"},
        case_id=task.case_id,
    )
    await email_service.persist_draft(db_session, task.id, "AI text", approval_id=str(approval.id))

    await db_session.refresh(task)
    assert (task.draft_sent, task.draft_text, task.draft_approval_id) == (
        True,
        "Thanks, we open at 9.",
        None,
    )
    assert (await _listed(client, front_desk_headers, task))["canApprove"] is False
    assert len(await events(db_session, "email.sent")) == 1


async def test_a_late_ai_draft_opens_no_review_item(db_session, client, front_desk_headers):
    task = await inbox_task(db_session)
    assert (await _reply(client, front_desk_headers, task)).status_code == 200

    approval = await approval_service.create_approval_request(
        db_session,
        action_type="email.draft_reply",
        payload={"task_id": str(task.id), "draft": "AI text"},
        case_id=task.case_id,
    )
    # Still created: a paused agent thread waits on it.
    assert approval.status == ApprovalStatus.PENDING
    items = await db_session.scalars(
        select(HumanReviewTask).where(HumanReviewTask.inbox_task_id == task.id)
    )
    assert items.all() == []


async def test_a_stale_task_elsewhere_does_not_send_twice(
    db_session, client, front_desk_headers, front_desk_user, detached_sessionmaker
):
    task = await inbox_task(db_session)
    email = (
        await db_session.execute(select(Email).where(Email.case_id == task.case_id))
    ).scalar_one()
    async with detached_sessionmaker() as other:
        # Loaded before the manual send, as draft_reply_detached loads it.
        stale = await other.get(Task, task.id)
        await other.commit()
        assert (await _reply(client, front_desk_headers, task)).status_code == 200
        assert stale is not None and stale.draft_sent is False  # out of date

        await email_service.deliver_reply(
            other,
            email_id=email.id,
            task_id=task.id,
            draft="AI text",
            actor=front_desk_user,
            case_id=task.case_id,
            automated=True,
        )
    assert len(await events(db_session, "email.sent")) == 1
    await db_session.refresh(task)
    assert task.draft_text == "Thanks, we open at 9."


async def test_a_late_flag_off_auto_send_is_not_a_send(
    db_session, client, front_desk_headers, front_desk_user, detached_sessionmaker, monkeypatch
):
    from app.models.user import User
    from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
    from tests.agent_fakes import DRAFT, FakeLLM

    task = await inbox_task(db_session)
    monkeypatch.setattr(email_service, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        email_service, "_generate_org_grounded_reply", AsyncMock(return_value=(DRAFT, True))
    )
    async with detached_sessionmaker() as other:
        # Loaded before the manual send, as draft_reply_detached loads it.
        stale = await other.get(Task, task.id)
        email = (
            await other.execute(select(Email).where(Email.case_id == task.case_id))
        ).scalar_one()
        actor = await other.get(User, front_desk_user.id)
        await other.commit()
        assert (await _reply(client, front_desk_headers, task)).status_code == 200

        outcome = await email_service.draft_reply(
            other,
            stale,
            email,
            actor,
            TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None),
            0.95,
        )

    assert (outcome.sent, outcome.approval_id) == (False, None)
    assert len(await events(db_session, "email.sent")) == 1
    await db_session.refresh(task)
    assert task.draft_text == "Thanks, we open at 9."


async def test_an_approved_reply_that_was_not_delivered_reopens_as_an_agent_failure(
    db_session, client, front_desk_headers, operator_headers, monkeypatch
):
    task = await _held(db_session, TaskCategory.GENERAL_ADMINISTRATIVE)
    email = (
        await db_session.execute(select(Email).where(Email.case_id == task.case_id))
    ).scalar_one()
    email.external_id = "AAMk-approved"
    await db_session.commit()
    monkeypatch.setattr(email_service.settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    monkeypatch.setattr(
        "app.services.outlook_client.send_reply",
        AsyncMock(side_effect=httpx.ConnectError("mail server down")),
    )

    response = await client.post(
        f"/api/v1/approvals/{task.draft_approval_id}/approve", json={}, headers=front_desk_headers
    )
    assert response.status_code == 502

    (item,) = (
        await db_session.scalars(
            select(HumanReviewTask).where(
                HumanReviewTask.inbox_task_id == task.id,
                HumanReviewTask.task_type == TaskType.AGENT_FAILURE,
            )
        )
    ).all()
    assert item.status == TaskStatus.PENDING
    assert "not delivered" in item.notes and "mail server down" in item.notes
    # The operator owns an agent failure, and the message opens for it to answer.
    opened = await client.get(f"/api/v1/inbox/{task.id}", headers=operator_headers)
    assert opened.status_code == 200
    assert opened.json()["canWriteReply"] is True
