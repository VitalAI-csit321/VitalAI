import pytest
from sqlalchemy import select

from app.models.email import Email
from app.models.task import Task, TaskCategory
from app.models.user import UserRole
from app.services import approval_service, human_review_service, task_service
from tests.review_helpers import assign, events, inbox_task


async def _held(db, category=TaskCategory.GENERAL_ADMINISTRATIVE, patient=None):
    task = await inbox_task(db, category=category, patient=patient)
    email = (await db.execute(select(Email).where(Email.case_id == task.case_id))).scalar_one()
    return await approval_service.create_approval_request(
        db,
        action_type="email.draft_reply",
        payload={"task_id": str(task.id), "email_id": str(email.id), "draft": "Hi"},
        case_id=task.case_id,
    )


async def _approve(client, approval, headers):
    return await client.post(f"/api/v1/approvals/{approval.id}/approve", json={}, headers=headers)


async def _reject(client, approval, headers):
    return await client.post(
        f"/api/v1/approvals/{approval.id}/reject", json={"notes": "no"}, headers=headers
    )


async def test_front_desk_approves_its_own_draft_only(client, db_session, front_desk_headers):
    own = await _held(db_session)  # general_administrative -> front desk
    other = await _held(db_session, TaskCategory.MEDICAL_RECORDS_REQUEST)  # operator
    assert (await _approve(client, own, front_desk_headers)).status_code == 200
    assert (await _approve(client, other, front_desk_headers)).status_code == 403
    assert await events(db_session, "governance.access_denied")


async def test_operator_approves_own_and_front_desk_drafts(client, db_session, operator_headers):
    assert (await _approve(client, await _held(db_session), operator_headers)).status_code == 200
    records = await _held(db_session, TaskCategory.MEDICAL_RECORDS_REQUEST)
    assert (await _approve(client, records, operator_headers)).status_code == 200


async def test_operator_cannot_approve_a_doctors_draft(
    client, db_session, operator_headers, patient, doctor_user
):
    await assign(db_session, doctor_user, patient)
    held = await _held(db_session, TaskCategory.PRESCRIPTION_RENEWAL, patient)
    assert (await _approve(client, held, operator_headers)).status_code == 403


async def test_doctor_approves_own_patients_draft_only(
    client, db_session, doctor_headers, doctor_user, patient
):
    from datetime import date

    from app.models.patient import Gender, Patient, PatientStatus

    await assign(db_session, doctor_user, patient)
    mine = await _held(db_session, TaskCategory.PRESCRIPTION_RENEWAL, patient)
    stranger = Patient(
        mrn="MRN-OTHER01",
        name="Other Person",
        dob=date(1980, 2, 2),
        gender=Gender.MALE,
        status=PatientStatus.ACTIVE,
    )
    db_session.add(stranger)
    await db_session.commit()
    other = await _held(
        db_session, TaskCategory.PRESCRIPTION_RENEWAL, stranger
    )  # no doctor -> operator
    assert (await _approve(client, mine, doctor_headers)).status_code == 200
    assert (await _approve(client, other, doctor_headers)).status_code == 403


async def test_admin_approves_anything(client, db_session, admin_headers, patient, doctor_user):
    await assign(db_session, doctor_user, patient)
    held = await _held(db_session, TaskCategory.PRESCRIPTION_RENEWAL, patient)
    assert (await _approve(client, held, admin_headers)).status_code == 200


async def test_operator_rejects_but_cannot_approve_clinical_text(
    client, db_session, operator_headers
):
    referral = await _held(db_session, TaskCategory.REFERRAL_REQUEST)  # operator queue, clinical
    assert (await _approve(client, referral, operator_headers)).status_code == 403
    response = await client.post(
        f"/api/v1/approvals/{referral.id}/reject",
        json={"notes": "wrong clinic"},
        headers=operator_headers,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("role", [UserRole.FRONT_DESK, UserRole.DOCTOR])
async def test_unlinked_approvals_stay_operator_and_admin(client, db_session, role_headers, role):
    request = await approval_service.create_approval_request(
        db_session, action_type="patient.assignment.suggested", payload={}
    )
    response = await client.post(
        f"/api/v1/approvals/{request.id}/approve", json={}, headers=role_headers[role]
    )
    assert response.status_code == 403


async def test_operator_sees_front_desk_items(client, db_session, operator_headers):
    await _held(db_session)
    body = (await client.get("/api/v1/human-review", headers=operator_headers)).json()
    assert [i["task_type"] for i in body["items"]] == ["draft_approval"]


async def test_front_desk_rejects_its_own_draft_only(client, db_session, front_desk_headers):
    own = await _held(db_session)  # general_administrative -> front desk
    other = await _held(db_session, TaskCategory.MEDICAL_RECORDS_REQUEST)  # operator
    assert (await _reject(client, own, front_desk_headers)).status_code == 200
    assert (await _reject(client, other, front_desk_headers)).status_code == 403


async def test_approve_cannot_redirect_delivery_via_resolved_payload(
    client, db_session, front_desk_headers
):
    """Regression, Task 4 fix round 1 CRITICAL 2. resolved_payload is a
    free-form dict the approver may edit (e.g. to fix a typo in the draft),
    but email_id/task_id must always come from the original request.payload -
    otherwise an approver authorised only on their own item could redirect
    delivery (and draft_sent) to a message they have no claim on."""
    own_task = await inbox_task(db_session)  # general_administrative -> front desk
    own_email = (
        await db_session.execute(select(Email).where(Email.case_id == own_task.case_id))
    ).scalar_one()
    approval = await approval_service.create_approval_request(
        db_session,
        action_type="email.draft_reply",
        payload={"task_id": str(own_task.id), "email_id": str(own_email.id), "draft": "Hi"},
        case_id=own_task.case_id,
    )

    other_task = await inbox_task(db_session, category=TaskCategory.MEDICAL_RECORDS_REQUEST)
    other_email = (
        await db_session.execute(select(Email).where(Email.case_id == other_task.case_id))
    ).scalar_one()

    response = await client.post(
        f"/api/v1/approvals/{approval.id}/approve",
        json={
            "resolved_payload": {
                "email_id": str(other_email.id),
                "task_id": str(other_task.id),
                "draft": "redirected",
            }
        },
        headers=front_desk_headers,
    )

    assert response.status_code == 200
    await db_session.refresh(other_task)
    await db_session.refresh(own_task)
    assert other_task.draft_sent is False
    assert own_task.draft_sent is True


async def test_operator_cannot_approve_clinical_draft_after_category_override(
    client, db_session, operator_headers, operator_user
):
    """Regression, Task 4 fix round 1 IMPORTANT 3. The clinical check must
    not look only at the inbox task's CURRENT category - an operator can
    retarget it after the draft is drawn up (POST /tasks/{id}/override) and
    launder a clinical reply through the relabel."""
    referral = await _held(db_session, TaskCategory.REFERRAL_REQUEST)  # operator queue, clinical
    item = await human_review_service.item_for_approval(db_session, referral.id)
    inbox = await db_session.get(Task, item.inbox_task_id)
    await task_service.override_task(
        db_session, inbox.id, TaskCategory.MEDICAL_RECORDS_REQUEST, "wrong clinic", operator_user
    )

    assert (await _approve(client, referral, operator_headers)).status_code == 403
