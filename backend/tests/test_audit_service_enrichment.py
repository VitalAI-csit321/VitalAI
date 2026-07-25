import pytest

from app.audit_context import reset_audit_context, set_audit_context
from app.auth.security import hash_password
from app.models.user import User, UserRole
from app.services.audit_service import record_event, risk_level_from_score


@pytest.mark.parametrize(
    "score,expected",
    [
        (None, "Low"),
        (0, "Low"),
        (29, "Low"),
        (30, "Medium"),
        (69, "Medium"),
        (70, "High"),
        (95, "High"),
    ],
)
def test_risk_level_from_score(score, expected):
    assert risk_level_from_score(score) == expected


@pytest.mark.parametrize(
    "action,expected_score,expected_outcome",
    [
        ("governance.access_denied", 90, "BLOCKED"),
        ("governance.input_blocked", 90, "BLOCKED"),
        ("task.escalation_review", 50, "SUCCESS"),
        ("triage.performed", 50, "SUCCESS"),
        ("routing.decided", 50, "SUCCESS"),
        ("intake.created", 10, "SUCCESS"),
        ("consent.captured", 10, "SUCCESS"),
    ],
)
async def test_record_event_computes_risk_and_outcome(
    db_session, action, expected_score, expected_outcome
):
    user = User(
        email=f"enrich-{action.replace('.', '-')}@example.com",
        hashed_password=hash_password("pw"),
        full_name="Enrichment Tester",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    event = await record_event(db_session, actor=user, action=action, details={})

    assert event.risk_score == expected_score
    assert event.outcome == expected_outcome
    assert event.actor_role == "admin"


async def test_record_event_reads_ip_and_session_from_context(db_session):
    user = User(
        email="context-tester@example.com",
        hashed_password=hash_password("pw"),
        full_name="Context Tester",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    ip_token, session_token = set_audit_context(ip_address="203.0.113.5", session_id="sess-xyz")
    try:
        event = await record_event(db_session, actor=user, action="intake.created", details={})
    finally:
        reset_audit_context(ip_token, session_token)

    assert event.ip_address == "203.0.113.5"
    assert event.session_id == "sess-xyz"


async def test_record_event_actor_role_none_when_no_actor(db_session):
    event = await record_event(db_session, actor=None, action="intake.created", details={})
    assert event.actor_role is None


async def test_record_event_actor_label_override(db_session):
    event = await record_event(
        db_session, actor=None, actor_label="dr_house", action="retrieval.performed", details={}
    )
    assert event.actor_label == "dr_house"
    assert event.actor_id is None
