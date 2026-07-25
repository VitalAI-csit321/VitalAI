import uuid

import pytest
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
from app.services import human_review_service
from app.services.human_review_service import (
    HumanReviewTaskNotFoundError,
    HumanReviewTaskWrongRoleError,
    HumanReviewTaskWrongStateError,
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
    db_session: AsyncSession, patient: Patient, front_desk_user: User
):
    case = await _make_case(db_session, patient)
    await _make_task(db_session, case, UserRole.FRONT_DESK)
    await _make_task(db_session, case, UserRole.FRONT_DESK)
    await _make_task(db_session, case, UserRole.OPERATOR)

    items, total = await human_review_service.list_tasks(db_session, front_desk_user)

    assert total == 2
    assert all(t.target_role == UserRole.FRONT_DESK for t in items)


async def test_list_tasks_filters_by_status(
    db_session: AsyncSession, patient: Patient, front_desk_user: User
):
    case = await _make_case(db_session, patient)
    await _make_task(db_session, case, UserRole.FRONT_DESK, status=TaskStatus.PENDING)
    await _make_task(db_session, case, UserRole.FRONT_DESK, status=TaskStatus.COMPLETED)

    items, total = await human_review_service.list_tasks(
        db_session, front_desk_user, status=TaskStatus.PENDING
    )

    assert total == 1
    assert items[0].status == TaskStatus.PENDING


async def test_list_tasks_doctor_sees_only_assigned_patients(
    db_session: AsyncSession, patient: Patient, doctor_user: User
):
    assigned_case = await _make_case(db_session, patient)
    await _make_task(db_session, assigned_case, UserRole.DOCTOR)
    await _assign(db_session, doctor_user, patient)

    other_patient = Patient(
        mrn="MRN-OTHERDOC01",
        name="Unassigned Patient",
        dob=patient.dob,
        gender=patient.gender,
        status=patient.status,
    )
    db_session.add(other_patient)
    await db_session.commit()
    await db_session.refresh(other_patient)
    other_case = await _make_case(db_session, other_patient)
    await _make_task(db_session, other_case, UserRole.DOCTOR)

    items, total = await human_review_service.list_tasks(db_session, doctor_user)

    assert total == 1
    assert items[0].case_id == assigned_case.id


async def test_list_tasks_doctor_sees_nothing_when_unassigned(
    db_session: AsyncSession, patient: Patient, doctor_user: User
):
    case = await _make_case(db_session, patient)
    await _make_task(db_session, case, UserRole.DOCTOR)

    items, total = await human_review_service.list_tasks(db_session, doctor_user)

    assert total == 0
    assert items == []


async def test_claim_task_success(
    db_session: AsyncSession, patient: Patient, front_desk_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    claimed = await human_review_service.claim_task(db_session, task.id, front_desk_user)

    assert claimed.status == TaskStatus.IN_PROGRESS
    assert claimed.assigned_to == front_desk_user.id


async def test_claim_task_wrong_role_raises(
    db_session: AsyncSession, patient: Patient, operator_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    with pytest.raises(HumanReviewTaskWrongRoleError):
        await human_review_service.claim_task(db_session, task.id, operator_user)


async def test_claim_task_doctor_allowed_when_assigned(
    db_session: AsyncSession, patient: Patient, doctor_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.DOCTOR)
    await _assign(db_session, doctor_user, patient)

    claimed = await human_review_service.claim_task(db_session, task.id, doctor_user)

    assert claimed.status == TaskStatus.IN_PROGRESS
    assert claimed.assigned_to == doctor_user.id


async def test_claim_task_doctor_denied_when_not_assigned(
    db_session: AsyncSession, patient: Patient, doctor_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.DOCTOR)

    with pytest.raises(HumanReviewTaskWrongRoleError):
        await human_review_service.claim_task(db_session, task.id, doctor_user)


async def test_claim_task_already_claimed_raises(
    db_session: AsyncSession, patient: Patient, front_desk_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)
    await human_review_service.claim_task(db_session, task.id, front_desk_user)

    with pytest.raises(HumanReviewTaskWrongStateError):
        await human_review_service.claim_task(db_session, task.id, front_desk_user)


async def test_claim_task_missing_raises(db_session: AsyncSession, front_desk_user: User):
    with pytest.raises(HumanReviewTaskNotFoundError):
        await human_review_service.claim_task(db_session, uuid.uuid4(), front_desk_user)


async def test_complete_task_success(
    db_session: AsyncSession, patient: Patient, front_desk_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)
    await human_review_service.claim_task(db_session, task.id, front_desk_user)

    completed = await human_review_service.complete_task(
        db_session, task.id, front_desk_user, notes="handled"
    )

    assert completed.status == TaskStatus.COMPLETED
    assert completed.notes == "handled"


async def test_complete_task_doctor_denied_when_not_assigned(
    db_session: AsyncSession, patient: Patient, doctor_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.DOCTOR, status=TaskStatus.IN_PROGRESS)

    with pytest.raises(HumanReviewTaskWrongRoleError):
        await human_review_service.complete_task(db_session, task.id, doctor_user)


async def test_complete_task_not_claimed_raises(
    db_session: AsyncSession, patient: Patient, front_desk_user: User
):
    case = await _make_case(db_session, patient)
    task = await _make_task(db_session, case, UserRole.FRONT_DESK)

    with pytest.raises(HumanReviewTaskWrongStateError):
        await human_review_service.complete_task(db_session, task.id, front_desk_user)