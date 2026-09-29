from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth.security import create_access_token, hash_password
from app.config import settings
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.human_review import HumanReviewTask, TaskPriority, TaskStatus, TaskType
from app.models.patient import Patient
from app.models.task import TaskCategory, TaskItemStatus
from app.models.task import TaskPriority as InboxPriority
from app.models.user import User, UserRole
from app.services import approval_service, review_routing
from tests.review_helpers import assign, events, inbox_task


async def _item(
    db, kind=TaskType.AGENT_HANDOVER, category=TaskCategory.GENERAL_ADMINISTRATIVE, patient=None
):
    task = await inbox_task(db, category=category, patient=patient)
    item = await review_routing.open_item(db, kind=kind, inbox_task=task, reason="why", actor=None)
    await db.commit()
    return item, task


async def _post(client, item, action, headers, **body):
    return await client.post(f"/api/v1/human-review/{item.id}/{action}", json=body, headers=headers)


async def test_every_action_is_audited(client, db_session, front_desk_headers):
    item, _ = await _item(db_session)
    assert (await _post(client, item, "claim", front_desk_headers)).status_code == 200
    assert (
        await _post(client, item, "complete", front_desk_headers, notes="done")
    ).status_code == 200
    other, _ = await _item(db_session)
    await _post(client, other, "claim", front_desk_headers)
    assert (
        await _post(client, other, "reject", front_desk_headers, notes="spam")
    ).status_code == 200
    for action, review in (
        ("review.claimed", item),
        ("review.completed", item),
        ("review.dismissed", other),
    ):
        assert any(
            e.details["review_id"] == str(review.id) for e in await events(db_session, action)
        )


@pytest.mark.parametrize("action", ["reject", "escalate"])
async def test_whitespace_note_is_refused(client, db_session, front_desk_headers, action):
    item, _ = await _item(db_session)
    await _post(client, item, "claim", front_desk_headers)
    assert (await _post(client, item, action, front_desk_headers, notes="   ")).status_code == 422
    assert (await _post(client, item, action, front_desk_headers)).status_code == 422


@pytest.mark.parametrize(
    ("role", "to_role"),
    [(UserRole.FRONT_DESK, UserRole.OPERATOR), (UserRole.OPERATOR, UserRole.ADMIN)],
)
async def test_escalate_moves_up_one_level(client, db_session, role_headers, role, to_role):
    category = (
        TaskCategory.GENERAL_ADMINISTRATIVE
        if role == UserRole.FRONT_DESK
        else TaskCategory.MEDICAL_RECORDS_REQUEST
    )
    item, task = await _item(db_session, category=category)
    headers = role_headers[role]
    await _post(client, item, "claim", headers)
    response = await _post(client, item, "escalate", headers, notes="beyond me")
    assert response.status_code == 200
    await db_session.refresh(item)
    await db_session.refresh(task)
    assert (item.status, item.priority, item.target_role) == (
        TaskStatus.ESCALATED,
        TaskPriority.HIGH,
        to_role,
    )
    assert item.assigned_to is None
    assert item.details["escalation"]["note"] == "beyond me"
    assert item.details["escalation"]["by_role"] == role.value
    assert item.notes == "why"  # the reason stays for the next owner
    assert task.status == TaskItemStatus.ESCALATED
    assert len(await events(db_session, "task.escalated")) == 1
    (escalated,) = await events(db_session, "review.escalated")
    # from_role is the item's previous owner, which here is the escalating role.
    assert {k: escalated.details[k] for k in ("review_id", "kind", "from_role", "to_role")} == {
        "review_id": str(item.id),
        "kind": TaskType.AGENT_HANDOVER.value,
        "from_role": role.value,
        "to_role": to_role.value,
    }
    listed = (await client.get("/api/v1/human-review", headers=headers)).json()["items"]
    if role == UserRole.FRONT_DESK:
        assert listed == []  # it left the front desk's queue


async def test_doctor_escalation_goes_to_the_operator(
    client, db_session, doctor_headers, doctor_user, patient
):
    await assign(db_session, doctor_user, patient)
    item, _ = await _item(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    await _post(client, item, "claim", doctor_headers)
    assert (await _post(client, item, "escalate", doctor_headers, notes="leave")).status_code == 200
    await db_session.refresh(item)
    assert (item.target_role, item.assigned_to) == (UserRole.OPERATOR, None)


async def test_admin_has_no_escalate(client, db_session, admin_headers):
    item, _ = await _item(db_session)
    await _post(client, item, "claim", admin_headers)
    assert (await _post(client, item, "escalate", admin_headers, notes="x")).status_code == 403


async def test_escalate_skips_an_already_escalated_inbox_task(
    client, db_session, front_desk_headers
):
    item, task = await _item(db_session)
    task.status = TaskItemStatus.ESCALATED
    await db_session.commit()
    await _post(client, item, "claim", front_desk_headers)
    assert (await _post(client, item, "escalate", front_desk_headers, notes="x")).status_code == 200
    assert await events(db_session, "task.escalated") == []


async def test_new_owner_acts_on_an_escalated_item_without_claiming(
    client, db_session, front_desk_headers, operator_headers
):
    item, _ = await _item(db_session)
    await _post(client, item, "claim", front_desk_headers)
    await _post(client, item, "escalate", front_desk_headers, notes="x")
    assert (
        await _post(client, item, "complete", operator_headers, notes="handled")
    ).status_code == 200


async def test_draft_items_cannot_be_completed_or_dismissed_directly(
    client, db_session, front_desk_headers
):
    item, _ = await _item(db_session, kind=TaskType.DRAFT_APPROVAL)
    await _post(client, item, "claim", front_desk_headers)
    assert (await _post(client, item, "complete", front_desk_headers, notes="x")).status_code == 409
    assert (await _post(client, item, "reject", front_desk_headers, notes="x")).status_code == 409


async def test_reroute_changes_the_message_queue(client, db_session, operator_headers):
    item, task = await _item(db_session, kind=TaskType.ROUTING_REVIEW)
    response = await _post(
        client, item, "reroute", operator_headers, category="prescription_renewal"
    )
    assert response.status_code == 200
    await db_session.refresh(task)
    await db_session.refresh(item)
    assert (task.category, task.target_role) == (TaskCategory.PRESCRIPTION_RENEWAL, UserRole.DOCTOR)
    assert item.status == TaskStatus.COMPLETED
    (event,) = await events(db_session, "review.rerouted")
    assert event.details["new_category"] == "prescription_renewal"


async def test_reroute_to_urgent_escalates_the_message(client, db_session, operator_headers):
    # Intake escalates an urgent message on arrival (D9); a re-route there must too.
    item, task = await _item(db_session, kind=TaskType.ROUTING_REVIEW)
    response = await _post(client, item, "reroute", operator_headers, category="urgent_emergency")
    assert response.status_code == 200
    await db_session.refresh(task)
    assert (task.status, task.priority, task.target_role) == (
        TaskItemStatus.ESCALATED,
        InboxPriority.URGENT,
        UserRole.OPERATOR,
    )
    (event,) = await events(db_session, "task.escalated")
    assert event.details["reason"] == "rerouted: urgent_category"


async def test_reroute_to_complaint_opens_a_complaint_item(client, db_session, operator_headers):
    # Intake opens a complaint item (D10); a re-route there must too.
    item, task = await _item(db_session, kind=TaskType.ROUTING_REVIEW)
    response = await _post(
        client, item, "reroute", operator_headers, category="complaint_escalation"
    )
    assert response.status_code == 200
    (complaint,) = (
        await db_session.scalars(
            select(HumanReviewTask).where(
                HumanReviewTask.inbox_task_id == task.id,
                HumanReviewTask.task_type == TaskType.COMPLAINT_REVIEW,
            )
        )
    ).all()
    assert (complaint.status, complaint.target_role, complaint.priority, complaint.notes) == (
        TaskStatus.PENDING,
        UserRole.OPERATOR,
        TaskPriority.HIGH,
        "Complaint needs a response.",
    )


async def test_reroute_is_only_for_routing_items(client, db_session, front_desk_headers):
    item, _ = await _item(db_session)
    assert (
        await _post(
            client, item, "reroute", front_desk_headers, category="billing_insurance_enquiry"
        )
    ).status_code == 409


async def _identity_item(db, candidates):
    task = await inbox_task(db, category=TaskCategory.APPOINTMENT_REQUEST)
    item = await review_routing.open_item(
        db,
        kind=TaskType.IDENTITY_REVIEW,
        inbox_task=task,
        reason="who",
        actor=None,
        details={"outcome": "ambiguous", "candidates": [str(c) for c in candidates]},
    )
    await db.commit()
    return item


async def test_link_patient_from_the_candidates(client, db_session, front_desk_headers, patient):
    item = await _identity_item(db_session, [patient.id])
    assert (
        await _post(client, item, "link-patient", front_desk_headers, patient_id=str(patient.id))
    ).status_code == 200
    case = await db_session.get(IntakeCase, item.case_id)
    await db_session.refresh(case)
    assert case.patient_id == patient.id
    assert await events(db_session, "review.patient_linked")


async def test_link_refuses_a_patient_not_offered(client, db_session, front_desk_headers, patient):
    item = await _identity_item(db_session, [])
    response = await _post(
        client, item, "link-patient", front_desk_headers, patient_id=str(patient.id)
    )
    assert response.status_code == 422
    case = await db_session.get(IntakeCase, item.case_id)
    assert case.patient_id is None


async def test_link_refuses_a_case_already_linked_to_someone_else(
    client, db_session, front_desk_headers, patient
):
    other = Patient(
        mrn="MRN-LINKED01", name="Already Linked", dob=patient.dob, status=patient.status
    )
    db_session.add(other)
    await db_session.commit()
    item = await _identity_item(db_session, [patient.id])
    case = await db_session.get(IntakeCase, item.case_id)
    case.patient_id = other.id
    await db_session.commit()

    response = await _post(
        client, item, "link-patient", front_desk_headers, patient_id=str(patient.id)
    )
    assert response.status_code == 409
    await db_session.refresh(case)
    assert case.patient_id == other.id
    assert await events(db_session, "review.patient_linked") == []


async def test_none_of_these_closes_without_linking(
    client, db_session, front_desk_headers, patient
):
    item = await _identity_item(db_session, [patient.id])
    assert (
        await _post(client, item, "link-patient", front_desk_headers, patient_id=None)
    ).status_code == 200
    await db_session.refresh(item)
    assert item.status == TaskStatus.COMPLETED


async def test_due_at_uses_the_sla_settings(client, db_session, front_desk_headers, monkeypatch):
    item, _ = await _item(db_session)  # medium priority
    item.priority = TaskPriority.HIGH
    await db_session.commit()
    monkeypatch.setattr(settings, "review_sla_hours_high", 2)
    (row,) = (await client.get("/api/v1/human-review", headers=front_desk_headers)).json()["items"]
    from datetime import datetime

    assert datetime.fromisoformat(row["due_at"]) - datetime.fromisoformat(
        row["created_at"]
    ) == timedelta(hours=2)
    item.priority = TaskPriority.MEDIUM
    await db_session.commit()
    (row,) = (await client.get("/api/v1/human-review", headers=front_desk_headers)).json()["items"]
    assert datetime.fromisoformat(row["due_at"]) - datetime.fromisoformat(
        row["created_at"]
    ) == timedelta(hours=24)


async def test_row_shows_owner_channel_and_candidates(
    client, db_session, front_desk_headers, patient
):
    await _identity_item(db_session, [patient.id])
    (row,) = (await client.get("/api/v1/human-review", headers=front_desk_headers)).json()["items"]
    assert row["owner_label"] == "Front desk queue"
    assert row["channel"] == "email"
    assert row["candidates"] == [{"id": str(patient.id), "name": patient.name, "dob": "1990-01-01"}]


def test_sla_settings_are_editable():
    from app.services.settings_service import SETTINGS_REGISTRY

    assert SETTINGS_REGISTRY["review_sla_hours_high"].editable
    assert SETTINGS_REGISTRY["review_sla_hours_default"].group == "Approval tiers"


async def test_escalated_clinical_draft_is_reassigned_then_approved(
    client, db_session, doctor_headers, doctor_user, operator_headers, patient
):
    second = User(
        email="dr2@example.com",
        full_name="Dr Two",
        role=UserRole.DOCTOR,
        hashed_password=hash_password("pw12345678"),
    )
    db_session.add(second)
    await db_session.commit()
    await db_session.refresh(second)
    second_headers = {"Authorization": f"Bearer {create_access_token(second.id, second.role)}"}
    await assign(db_session, doctor_user, patient)
    task = await inbox_task(db_session, category=TaskCategory.PRESCRIPTION_RENEWAL, patient=patient)
    email = (
        await db_session.execute(select(Email).where(Email.case_id == task.case_id))
    ).scalar_one()
    approval = await approval_service.create_approval_request(
        db_session,
        action_type="email.draft_reply",
        payload={"task_id": str(task.id), "email_id": str(email.id), "draft": "Hi"},
        case_id=task.case_id,
    )
    (item,) = (
        (
            await db_session.execute(
                select(HumanReviewTask).where(HumanReviewTask.approval_id == approval.id)
            )
        )
        .scalars()
        .all()
    )
    await _post(client, item, "claim", doctor_headers)
    await _post(client, item, "escalate", doctor_headers, notes="on leave")
    assert (
        await client.post(
            f"/api/v1/approvals/{approval.id}/approve", json={}, headers=operator_headers
        )
    ).status_code == 403
    assert (
        await _post(client, item, "reassign", operator_headers, doctor_id=str(second.id))
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/approvals/{approval.id}/approve", json={}, headers=second_headers
        )
    ).status_code == 200
    assert await events(db_session, "review.reassigned")


async def test_reassign_needs_a_doctor(
    client, db_session, operator_headers, operator_user, front_desk_headers
):
    item, _ = await _item(
        db_session, kind=TaskType.DRAFT_APPROVAL, category=TaskCategory.MEDICAL_RECORDS_REQUEST
    )
    assert (
        await _post(client, item, "reassign", operator_headers, doctor_id=str(operator_user.id))
    ).status_code == 422
    fd_item, _ = await _item(db_session, kind=TaskType.DRAFT_APPROVAL)
    assert (
        await _post(
            client, fd_item, "reassign", front_desk_headers, doctor_id=str(operator_user.id)
        )
    ).status_code == 403
