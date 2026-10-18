import json
from typing import cast
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class _FakeLLM:
    """Answers the classifier's canned response, and answers WORTHY to the
    reply-worthiness gate's separate call -- these tests aren't exercising
    that gate (see test_reply_gate.py), they just need it out of the way.
    """

    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


def _mock_classifier(monkeypatch, category: str, confidence: float) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": category, "confidence": confidence})),
    )


async def _ingest(client: AsyncClient, headers: dict) -> dict:
    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("Reply body.", True)),
    ):
        response = await client.post(
            "/api/v1/email/ingest",
            json={
                "sender": "patient@example.com",
                "recipient": "clinic@example.com",
                "subject": "Question",
                "body": "What are your hours?",
            },
            headers=headers,
        )
    assert response.status_code == 201
    return cast(dict, response.json())


async def test_escalate_task_sets_urgent_and_escalated(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/escalate",
        json={"reason": "Needs a human"},
        headers=front_desk_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "escalated"
    assert body["priority"] == "urgent"


async def test_escalate_task_twice_returns_409(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    await client.post(f"/api/v1/tasks/{task_id}/escalate", json={}, headers=front_desk_headers)
    second = await client.post(
        f"/api/v1/tasks/{task_id}/escalate", json={}, headers=front_desk_headers
    )

    assert second.status_code == 409


async def test_archive_task_removes_it_from_inbox(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    archive = await client.post(f"/api/v1/tasks/{task_id}/archive", headers=front_desk_headers)
    assert archive.status_code == 200
    assert archive.json()["status"] == "completed"

    inbox = await client.get("/api/v1/inbox", headers=front_desk_headers)
    assert not any(m["id"] == task_id for m in inbox.json()["items"])


async def test_escalate_and_archive_require_auth(client: AsyncClient):
    import uuid

    task_id = str(uuid.uuid4())
    escalate = await client.post(f"/api/v1/tasks/{task_id}/escalate", json={})
    archive = await client.post(f"/api/v1/tasks/{task_id}/archive")
    assert escalate.status_code == 401
    assert archive.status_code == 401


async def test_escalate_denied_when_task_targets_a_different_role(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    # prescription_renewal resolves to UserRole.DOCTOR, not front_desk's own role.
    _mock_classifier(monkeypatch, "prescription_renewal", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/escalate", json={}, headers=front_desk_headers
    )

    assert response.status_code == 403


async def test_archive_denied_for_doctor_unassigned_to_the_patient(
    client: AsyncClient, front_desk_headers: dict, doctor_headers: dict, monkeypatch
):
    # prescription_renewal resolves to UserRole.DOCTOR, but this doctor has no
    # assignment to the patient behind the ingested email's case.
    _mock_classifier(monkeypatch, "prescription_renewal", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.post(f"/api/v1/tasks/{task_id}/archive", headers=doctor_headers)

    assert response.status_code == 403


async def test_inbox_surfaces_persisted_draft(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)

    inbox = await client.get("/api/v1/inbox", headers=front_desk_headers)
    item = next(m for m in inbox.json()["items"] if m["id"] == ingest["task_id"])

    assert item["draftText"] == "Reply body."
    assert item["draftSent"] is True
    assert item["taskStatus"] == "pending"


async def test_admin_can_delete_task(client: AsyncClient, admin_headers: dict, monkeypatch):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)

    assert response.status_code == 200


async def test_operator_can_delete_task(client: AsyncClient, operator_headers: dict, monkeypatch):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, operator_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=operator_headers)

    assert response.status_code == 200


async def test_front_desk_cannot_delete_task(
    client: AsyncClient, front_desk_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=front_desk_headers)

    assert response.status_code == 403


async def test_doctor_cannot_delete_task(
    client: AsyncClient, front_desk_headers: dict, doctor_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, front_desk_headers)
    task_id = ingest["task_id"]

    response = await client.delete(f"/api/v1/tasks/{task_id}", headers=doctor_headers)

    assert response.status_code == 403


async def test_deleted_task_is_invisible_in_inbox_and_archived_view(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    delete = await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)
    assert delete.status_code == 200

    inbox = await client.get("/api/v1/inbox", headers=admin_headers)
    archived = await client.get("/api/v1/inbox?archived=true", headers=admin_headers)

    assert not any(m["id"] == task_id for m in inbox.json()["items"])
    assert not any(m["id"] == task_id for m in archived.json()["items"])


async def test_deleted_task_is_invisible_in_task_list(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    """GET /tasks feeds the inbox urgent-call banner and the Escalations board."""
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)

    tasks = await client.get("/api/v1/tasks", headers=admin_headers)

    assert not any(t["id"] == task_id for t in tasks.json())


async def test_deleted_task_stays_invisible_even_after_archiving(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    """Soft delete must win over archive/completed status in both views."""
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    await client.post(f"/api/v1/tasks/{task_id}/archive", headers=admin_headers)
    await client.delete(f"/api/v1/tasks/{task_id}", headers=admin_headers)

    archived = await client.get("/api/v1/inbox?archived=true", headers=admin_headers)

    assert not any(m["id"] == task_id for m in archived.json()["items"])


async def test_archived_view_returns_only_completed_tasks(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    pending = await _ingest(client, admin_headers)
    to_archive = await _ingest(client, admin_headers)
    await client.post(f"/api/v1/tasks/{to_archive['task_id']}/archive", headers=admin_headers)

    archived = await client.get("/api/v1/inbox?archived=true", headers=admin_headers)
    archived_ids = {m["id"] for m in archived.json()["items"]}

    assert to_archive["task_id"] in archived_ids
    assert pending["task_id"] not in archived_ids


async def test_task_starts_unread_and_flips_after_marking_read(
    client: AsyncClient, admin_headers: dict, monkeypatch
):
    _mock_classifier(monkeypatch, "general_administrative", 0.95)
    ingest = await _ingest(client, admin_headers)
    task_id = ingest["task_id"]

    before = await client.get("/api/v1/inbox", headers=admin_headers)
    item_before = next(m for m in before.json()["items"] if m["id"] == task_id)
    assert item_before["unread"] is True

    mark_read = await client.post(f"/api/v1/tasks/{task_id}/read", headers=admin_headers)
    assert mark_read.status_code == 200

    after = await client.get("/api/v1/inbox", headers=admin_headers)
    item_after = next(m for m in after.json()["items"] if m["id"] == task_id)
    assert item_after["unread"] is False


async def _message_with_open_review_item(db):
    from app.models.human_review import TaskType
    from app.services import review_routing
    from tests.review_helpers import inbox_task

    task = await inbox_task(db)
    item = await review_routing.open_item(
        db, kind=TaskType.INTENT_REVIEW, inbox_task=task, reason="why", actor=None
    )
    await db.commit()
    return task, item


async def _open_items_for(db, task_id):
    from sqlalchemy import select

    from app.models.human_review import HumanReviewTask
    from app.services import review_routing

    return (
        await db.scalars(
            select(HumanReviewTask).where(
                HumanReviewTask.inbox_task_id == task_id,
                HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
            )
        )
    ).all()


async def test_archiving_a_message_closes_its_review_queue_items(
    db_session, client: AsyncClient, front_desk_headers: dict
):
    from tests.review_helpers import events

    task, item = await _message_with_open_review_item(db_session)

    archive = await client.post(f"/api/v1/tasks/{task.id}/archive", headers=front_desk_headers)
    assert archive.status_code == 200

    assert await _open_items_for(db_session, task.id) == []
    closed = [
        e
        for e in await events(db_session, "review.completed")
        if e.details["review_id"] == str(item.id)
    ]
    assert len(closed) == 1 and closed[0].details["note"] == "Message archived"


async def test_deleting_a_message_closes_its_review_queue_items(
    db_session, client: AsyncClient, admin_headers: dict
):
    task, _item = await _message_with_open_review_item(db_session)

    delete = await client.delete(f"/api/v1/tasks/{task.id}", headers=admin_headers)
    assert delete.status_code in (200, 204)

    assert await _open_items_for(db_session, task.id) == []


async def test_archiving_leaves_a_held_draft_and_a_case_choice_open(
    db_session, client: AsyncClient, front_desk_headers: dict
):
    """A held draft is settled only by approve or reject (the clinical-approver
    rule lives there), and a case choice is about filing the contact, which
    outlives the inbox message. Neither is closed by an archive."""
    from app.models.approval import ApprovalStatus
    from app.models.human_review import TaskType
    from app.models.task import TaskCategory
    from app.services import approval_service, review_routing
    from tests.test_inbox import _held

    task = await _held(db_session, TaskCategory.GENERAL_ADMINISTRATIVE)
    draft_item = await review_routing.open_item(
        db_session,
        kind=TaskType.DRAFT_APPROVAL,
        inbox_task=task,
        reason="held",
        actor=None,
        approval_id=task.draft_approval_id,
    )
    choice_item = await review_routing.open_item(
        db_session, kind=TaskType.CASE_CHOICE, inbox_task=task, reason="which case", actor=None
    )
    intent_item = await review_routing.open_item(
        db_session, kind=TaskType.INTENT_REVIEW, inbox_task=task, reason="unsure", actor=None
    )
    await db_session.commit()

    archive = await client.post(f"/api/v1/tasks/{task.id}/archive", headers=front_desk_headers)
    assert archive.status_code == 200

    still_open = {i.id for i in await _open_items_for(db_session, task.id)}
    assert still_open == {draft_item.id, choice_item.id}
    assert intent_item.id not in still_open
    await db_session.refresh(task)
    approval = await approval_service.get_approval(db_session, task.draft_approval_id)
    assert approval.status == ApprovalStatus.PENDING
