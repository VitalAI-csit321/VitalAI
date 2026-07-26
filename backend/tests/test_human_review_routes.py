import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DoctorPatientAssignment,
    HumanReviewTask,
    IntakeCase,
    Patient,
    TaskStatus,
    TaskType,
    User,
    UserRole,
)


async def _make_case(db_session: AsyncSession, patient: Patient) -> IntakeCase:
    case = IntakeCase(patient_id=patient.id, contact_reason="test", contact_channel="phone")
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)
    return case


async def _make_task(
    db_session: AsyncSession,
    case: IntakeCase,
    target_role: UserRole,
    status: TaskStatus = TaskStatus.PENDING,
) -> HumanReviewTask:
    task = HumanReviewTask(
        case_id=case.id,
        task_type=TaskType.ROUTING_REVIEW,
        target_role=target_role,
        status=status,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


async def _assign(db_session: AsyncSession, doctor: User, patient: Patient) -> None:
    db_session.add(
        DoctorPatientAssignment(doctor_id=doctor.id, patient_id=patient.id, assigned_by=doctor.id)
    )
    await db_session.commit()


async def test_list_tasks_scoped_to_actor_role(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    await _make_task(db_session, case, UserRole.FRONT_DESK)
    await _make_task(db_session, case, UserRole.FRONT_DESK)
    await _make_task(db_session, case, UserRole.OPERATOR)

    response = await client.get("/api/v1/human-review", headers=front_desk_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


async def test_list_tasks_doctor_sees_only_assigned(
    client: AsyncClient,
    doctor_headers: dict,
    db_session: AsyncSession,
    patient: Patient,
    doctor_user: User,
):
    case = await _make_case(db_session, patient)
    await _make_task(db_session, case, UserRole.DOCTOR)
    await _assign(db_session, doctor_user, patient)

    response = await client.get("/api/v1/human-review", headers=doctor_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_list_tasks_doctor_empty_when_unassigned(
    client: AsyncClient, doctor_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    await _make_task(db_session, case, UserRole.DOCTOR)

    response = await client.get("/api/v1/human-review", headers=doctor_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_claim_task_success(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/claim", headers=front_desk_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"


async def test_claim_task_wrong_role_returns_403(
    client: AsyncClient, operator_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    response = await client.post(f"/api/v1/human-review/{task.id}/claim", headers=operator_headers)

    assert response.status_code == 403


async def test_claim_task_doctor_allowed_when_assigned(
    client: AsyncClient,
    doctor_headers: dict,
    db_session: AsyncSession,
    patient: Patient,
    doctor_user: User,
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.DOCTOR)
    await _assign(db_session, doctor_user, patient)

    response = await client.post(f"/api/v1/human-review/{task.id}/claim", headers=doctor_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


async def test_claim_task_doctor_denied_when_not_assigned(
    client: AsyncClient, doctor_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.DOCTOR)

    response = await client.post(f"/api/v1/human-review/{task.id}/claim", headers=doctor_headers)

    assert response.status_code == 403


async def test_claim_task_missing_returns_404(client: AsyncClient, front_desk_headers: dict):
    response = await client.post(
        f"/api/v1/human-review/{uuid.uuid4()}/claim", headers=front_desk_headers
    )
    assert response.status_code == 404


async def test_claim_task_already_claimed_returns_409(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)
    first = await client.post(f"/api/v1/human-review/{task.id}/claim", headers=front_desk_headers)
    assert first.status_code == 200

    second = await client.post(f"/api/v1/human-review/{task.id}/claim", headers=front_desk_headers)
    assert second.status_code == 409


async def test_complete_task_success(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)
    await client.post(f"/api/v1/human-review/{task.id}/claim", headers=front_desk_headers)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/complete",
        json={"notes": "resolved"},
        headers=front_desk_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["notes"] == "resolved"


async def test_complete_task_not_claimed_returns_409(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/complete", json={}, headers=front_desk_headers
    )

    assert response.status_code == 409


async def test_reject_endpoint_transitions_to_cancelled(
    client: AsyncClient, db_session: AsyncSession, patient: Patient, front_desk_headers: dict
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK, status=TaskStatus.IN_PROGRESS)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/reject",
        json={"notes": "Rejected: no evidence"},
        headers=front_desk_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["notes"] == "Rejected: no evidence"


async def test_reject_endpoint_not_claimed_returns_409(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/reject", json={}, headers=front_desk_headers
    )

    assert response.status_code == 409


async def test_reject_endpoint_missing_task_returns_404(
    client: AsyncClient, front_desk_headers: dict
):
    response = await client.post(
        f"/api/v1/human-review/{uuid.uuid4()}/reject", json={}, headers=front_desk_headers
    )

    assert response.status_code == 404


async def test_escalate_endpoint_transitions_to_escalated(
    client: AsyncClient, db_session: AsyncSession, patient: Patient, front_desk_headers: dict
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK, status=TaskStatus.IN_PROGRESS)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/escalate",
        json={"notes": "Escalating: needs senior review"},
        headers=front_desk_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "escalated"
    assert body["notes"] == "Escalating: needs senior review"


async def test_escalate_endpoint_not_claimed_returns_409(
    client: AsyncClient, front_desk_headers: dict, db_session: AsyncSession, patient: Patient
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    response = await client.post(
        f"/api/v1/human-review/{task.id}/escalate", json={}, headers=front_desk_headers
    )

    assert response.status_code == 409


async def test_escalate_endpoint_missing_task_returns_404(
    client: AsyncClient, front_desk_headers: dict
):
    response = await client.post(
        f"/api/v1/human-review/{uuid.uuid4()}/escalate", json={}, headers=front_desk_headers
    )

    assert response.status_code == 404
