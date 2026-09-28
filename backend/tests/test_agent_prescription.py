"""The prescription branch (build spec §12, as narrowed by G.16).

Two things are being defended here and they are different. The agent MAY
read clinical data, through a permission a human granted it and can revoke.
The agent may NOT put clinical data in an email. §12 is the only branch where
both halves are live at once.

The service-layer permission check matters because the agent path has no
route: require_permission is a FastAPI dependency and a graph run never
passes through one.
"""

import re
from datetime import date, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents.graph import build_graph, run_config, thread_id
from app.auth.permissions import VIEW_CLINICAL
from app.config import settings
from app.llm.output_guardrail import RESTRICTED_TERMS
from app.models.approval import ApprovalRequest
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.medication import Medication, MedicationStatus
from app.models.patient import Gender, Patient, PatientStatus
from app.models.permission_grant import UserPermissionGrant
from app.models.task import Task, TaskCategory
from app.models.user import User, UserRole
from app.services import medication_service, prescription_service
from app.services.draft_critic import SUITABILITY_REASON, critique
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
from tests.agent_fakes import FakeLLM, seed_email

AUTO = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)
MEDICINE = "Insulin glargine"


@pytest.fixture
def guards(monkeypatch):
    """Every route to a model, retrieval or a mailbox made loud."""
    llm = FakeLLM(worthy=True)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_reply", sends)
    mails = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_mail", mails)
    for target in (
        "app.rag.retrieval.retrieve",
        "app.rag.answer.answer_question",
        "app.services.email_service.generate_draft",
    ):
        monkeypatch.setattr(target, AsyncMock(side_effect=AssertionError(f"{target} called")))
    return llm, sends, mails


def _user(role: UserRole) -> User:
    return User(
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        hashed_password="h",
        full_name="Test Person",
        role=role,
    )


async def _add_user(db, role: UserRole) -> User:
    """Add, commit, and refresh.

    The refresh is the point: expire_on_commit leaves the instance expired, so
    the first attribute read would attempt IO outside the greenlet and raise
    MissingGreenlet. Nothing in the app hits this, because every real caller
    loads its actor with db.get and User.permission_grants is lazy="selectin",
    but a hand-built test object is not loaded that way.
    """
    user = _user(role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _patient(db, **extra) -> Patient:
    patient = Patient(
        mrn=f"MRN-RX{uuid4().hex[:6].upper()}",
        name=extra.pop("name", "Jane Smith"),
        dob=date(1985, 6, 1),
        gender=Gender.FEMALE,
        status=PatientStatus.ACTIVE,
        **extra,
    )
    db.add(patient)
    await db.commit()
    return patient


async def _linked_case(db, patient) -> IntakeCase:
    case = IntakeCase(
        patient_id=patient.id,
        patient_name=patient.name,
        contact_reason="Repeat request",
        contact_channel="email",
    )
    db.add(case)
    await db.commit()
    return case


async def _medication(db, patient, doctor, *, reviewed_days_ago=10, status=MedicationStatus.ACTIVE):
    med = Medication(
        patient_id=patient.id,
        name=MEDICINE,
        dosage="10 units",
        frequency="nightly",
        prescribed_by_id=doctor.id if doctor else None,
        prescribed_on=date.today() - timedelta(days=400),
        last_review_date=(
            None if reviewed_days_ago is None else date.today() - timedelta(days=reviewed_days_ago)
        ),
        status=status,
    )
    db.add(med)
    await db.commit()
    return med


async def _grant_clinical(db, target: User, admin: User) -> None:
    """Tests create the grant themselves: nothing here depends on the seed
    script having run."""
    db.add(UserPermissionGrant(user_id=target.id, permission=VIEW_CLINICAL, granted_by=admin.id))
    await db.commit()
    await db.refresh(target)


# --- 12.2: the service-layer permission check -------------------------------------------


async def test_medication_history_is_refused_by_the_service_not_a_route(db_session, admin_user):
    """No HTTP request anywhere in this test. require_permission is a route
    dependency, so if the refusal came from there the agent path would be
    entirely unguarded."""
    operator = await _add_user(db_session, UserRole.OPERATOR)
    patient = await _patient(db_session)
    await _medication(db_session, patient, None)

    with pytest.raises(medication_service.ClinicalAccessDeniedError):
        await medication_service.get_medication_history(db_session, patient.id, actor=operator)


async def test_an_explicit_grant_is_what_lets_the_agent_read(db_session, admin_user):
    """The governance claim: readable because a human granted it, and the
    same row being absent makes it unreadable again."""
    operator = await _add_user(db_session, UserRole.OPERATOR)
    patient = await _patient(db_session)
    await _medication(db_session, patient, None)

    await _grant_clinical(db_session, operator, admin_user)
    history = await medication_service.get_medication_history(
        db_session, patient.id, actor=operator
    )
    assert [m.name for m in history] == [MEDICINE]

    grant = await db_session.get(UserPermissionGrant, (operator.id, VIEW_CLINICAL))
    await db_session.delete(grant)
    await db_session.commit()
    await db_session.refresh(operator)
    with pytest.raises(medication_service.ClinicalAccessDeniedError):
        await medication_service.get_medication_history(db_session, patient.id, actor=operator)


async def test_a_doctor_needs_no_grant(db_session):
    doctor = await _add_user(db_session, UserRole.DOCTOR)
    patient = await _patient(db_session)
    await _medication(db_session, patient, doctor)

    assert await medication_service.get_medication_history(db_session, patient.id, actor=doctor)


# --- 12.3: which message, and what it must not say --------------------------------------


@pytest.mark.parametrize(
    "reviewed_days_ago, expected_due",
    [
        pytest.param(10, False, id="recently_reviewed"),
        pytest.param(400, True, id="review_is_stale"),
        pytest.param(None, True, id="never_reviewed"),
    ],
)
def test_check_last_review_date_reads_the_interval(reviewed_days_ago, expected_due):
    class _Med:
        status = MedicationStatus.ACTIVE
        last_review_date = (
            None if reviewed_days_ago is None else date.today() - timedelta(days=reviewed_days_ago)
        )

    assert medication_service.check_last_review_date([_Med()]) is expected_due


def test_nothing_active_means_a_review_is_due():
    """Pessimistic on purpose: no active medication is not evidence that a
    repeat is safe to arrange."""
    assert medication_service.check_last_review_date([]) is True


@pytest.mark.parametrize("review_due", [True, False])
def test_neither_draft_names_a_medicine_or_trips_the_guardrail(review_due):
    draft = prescription_service.draft_prescription_reply(name="Jane Smith", review_due=review_due)
    lowered = draft.lower()

    assert MEDICINE.lower() not in lowered
    assert "10 units" not in lowered
    assert "nightly" not in lowered
    # The guardrail would discard the draft entirely, so the patient would get
    # nothing at all. "prescription" is itself a restricted term.
    assert [term for term in RESTRICTED_TERMS if term in lowered] == []
    assert not re.search(r"\d", draft), draft
    assert "Hi Jane," in draft


def test_a_suitability_implying_draft_still_fails_the_critic():
    """The critic needs no new rule: _SUITABILITY_PHRASES already applies to
    every branch. This asserts it rather than duplicating it."""
    bad = "Hi Jane,\n\nIt is safe to continue taking this.\n\nKind regards,\nThe clinic team"
    assert critique(bad, branch=prescription_service.BRANCH) == SUITABILITY_REASON
    good = prescription_service.draft_prescription_reply(name="Jane Smith", review_due=False)
    assert critique(good, branch=prescription_service.BRANCH) is None


# --- the branch end to end --------------------------------------------------------------


async def _run(db, agent_saver, *, case_id, sender="jane@example.com"):
    email, task = await seed_email(
        db,
        category=TaskCategory.PRESCRIPTION_RENEWAL,
        case_id=case_id,
        sender=sender,
        body="Could I get a repeat of my usual please?",
        external_id=f"outlook-{uuid4()}",
    )
    await agent_graph.start(task.id, email.id, None, AUTO, 0.97)
    snapshot = (
        await build_graph()
        .compile(checkpointer=agent_saver)
        .aget_state(run_config(thread_id("email", str(email.id))))
    )
    await db.refresh(task)
    return email, task, snapshot


async def test_the_branch_drafts_raises_an_internal_task_and_never_auto_sends(
    db_session, agent_saver, guards, admin_user, doctor_user
):
    llm, sends, mails = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    await _medication(db_session, patient, doctor_user, reviewed_days_ago=10)
    agent = await _agent_actor(db_session, admin_user)

    email, task, snapshot = await _run(db_session, agent_saver, case_id=case.id)

    # First, before anything that could fail for another reason.
    sends.assert_not_awaited()
    mails.assert_not_awaited()
    assert task.draft_sent is False
    assert snapshot.next == ("await_approval",)

    values = snapshot.values
    assert values["branch"] == "prescription"
    assert values["risk_tier"] == "high"
    assert values["prescription_review_due"] is False
    assert llm.draft_prompts == []

    rows = (await db_session.execute(select(ApprovalRequest))).scalars().all()
    (approval,) = [r for r in rows if r.payload.get("task_id") == str(task.id)]
    draft = approval.payload["draft"]
    assert MEDICINE.lower() not in draft.lower()
    assert "passed to your doctor" in draft

    # The internal half: a Task for the prescriber, not an email.
    tasks = (await db_session.execute(select(Task).where(Task.case_id == case.id))).scalars().all()
    raised = [t for t in tasks if t.assigned_to == doctor_user.id]
    assert len(raised) == 1
    assert raised[0].target_role == UserRole.DOCTOR
    events = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert [e for e in events if e.action == "prescription.request_raised" and e.case_id == case.id]
    assert agent is not None


async def _agent_actor(db, admin_user):
    from app.services.system_actor import get_or_create_agent_actor

    agent = await get_or_create_agent_actor(db)
    # A new agent actor is granted this at creation; only add it if absent.
    if await db.get(UserPermissionGrant, (agent.id, VIEW_CLINICAL)) is None:
        await _grant_clinical(db, agent, admin_user)
    return agent


async def test_a_stale_review_changes_which_message_the_patient_gets(
    db_session, agent_saver, guards, admin_user, doctor_user
):
    _, sends, mails = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    await _medication(db_session, patient, doctor_user, reviewed_days_ago=400)
    await _agent_actor(db_session, admin_user)

    email, task, snapshot = await _run(db_session, agent_saver, case_id=case.id)

    sends.assert_not_awaited()
    mails.assert_not_awaited()
    assert snapshot.values["prescription_review_due"] is True
    assert "due a review" in snapshot.values["draft_text"]
    assert MEDICINE.lower() not in snapshot.values["draft_text"].lower()


async def test_a_provisional_patient_is_refused_outright(
    db_session, agent_saver, guards, admin_user, doctor_user
):
    """§12.3. The branch never runs, so no clinical read happens either."""
    _, sends, mails = guards
    patient = await _patient(db_session, is_provisional=True)
    case = await _linked_case(db_session, patient)
    await _medication(db_session, patient, doctor_user)
    await _agent_actor(db_session, admin_user)

    email, task, snapshot = await _run(db_session, agent_saver, case_id=case.id)

    sends.assert_not_awaited()
    mails.assert_not_awaited()
    assert task.draft_sent is False
    assert snapshot.values.get("branch") != "prescription"


async def test_the_node_fails_safe_when_the_grant_is_missing(
    db_session, agent_saver, guards, admin_user, doctor_user
):
    """No grant, so medication_service raises inside the node. _guarded must
    catch it, note the failure on the Task and end the run rather than
    drafting something or dying silently (F.43)."""
    _, sends, mails = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    await _medication(db_session, patient, doctor_user)
    # A new agent actor is granted VIEW_CLINICAL at creation; an admin has
    # since revoked it, which must stay a safe failure.
    from app.services.system_actor import get_or_create_agent_actor

    agent = await get_or_create_agent_actor(db_session)
    await db_session.delete(await db_session.get(UserPermissionGrant, (agent.id, VIEW_CLINICAL)))
    await db_session.commit()

    email, task, snapshot = await _run(db_session, agent_saver, case_id=case.id)

    sends.assert_not_awaited()
    mails.assert_not_awaited()
    assert task.draft_sent is False
    assert task.handover_context is not None
    events = (await db_session.execute(select(AuditEvent))).scalars().all()
    failures = [
        e
        for e in events
        if e.action == "agent.node_failed" and e.details.get("stage") == "prescription"
    ]
    assert len(failures) == 1
