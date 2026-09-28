"""The registration link's own rules (patient_form_service), without the graph."""

from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.task import TaskCategory
from app.services import patient_form_service
from tests.agent_fakes import seed_email


@pytest.fixture(autouse=True)
def frontend_origin(monkeypatch):
    monkeypatch.setattr(
        settings, "cors_origins", "https://app.clinic.example,http://localhost:5173"
    )


async def _open_link(
    db, *, sent_days_ago: float | None = 0, stage=ConversationStage.AWAITING_DETAILS
):
    email, _ = await seed_email(
        db, category=TaskCategory.APPOINTMENT_REQUEST, sender="jane@example.com"
    )
    row = EmailConversation(
        case_id=email.case_id,
        original_intent=TaskCategory.APPOINTMENT_REQUEST.value,
        origin_email_id=email.id,
        stage=stage.value,
        offered_slots=[],
        clarifications=0,
    )
    db.add(row)
    await db.flush()
    link = patient_form_service.issue_link(row)
    if sent_days_ago is not None:
        row.form_sent_at = datetime.now(UTC) - timedelta(days=sent_days_ago)
    await db.commit()
    return row, link.rsplit("/", 1)[1], link


async def test_the_link_is_built_on_the_frontend_origin_and_only_its_hash_is_kept(db_session):
    row, token, link = await _open_link(db_session)

    assert link == f"https://app.clinic.example/register/{token}"
    assert len(token) >= 40
    assert row.form_token_hash == patient_form_service.token_hash(token)
    assert token not in row.form_token_hash


async def test_a_sent_unused_link_is_open(db_session):
    row, token, _ = await _open_link(db_session, sent_days_ago=6.9)

    assert (await patient_form_service.find_open(db_session, token)).id == row.id


@pytest.mark.parametrize("token", ["", "nope", "x" * 500])
async def test_an_unknown_token_is_not_open(db_session, token):
    await _open_link(db_session)

    assert await patient_form_service.find_open(db_session, token) is None


async def test_a_link_older_than_seven_days_is_not_open(db_session):
    _, token, _ = await _open_link(db_session, sent_days_ago=7.01)

    assert await patient_form_service.find_open(db_session, token) is None


async def test_a_link_whose_email_never_went_out_is_not_open(db_session):
    _, token, _ = await _open_link(db_session, sent_days_ago=None)

    assert await patient_form_service.find_open(db_session, token) is None


async def test_a_used_link_is_not_open(db_session):
    row, token, _ = await _open_link(db_session)
    row.form_submitted_at = datetime.now(UTC)
    await db_session.commit()

    assert await patient_form_service.find_open(db_session, token) is None


@pytest.mark.parametrize(
    "stage", [ConversationStage.AWAITING_CHOICE, ConversationStage.BOOKED, ConversationStage.STAFF]
)
async def test_a_conversation_that_moved_on_closes_the_link(db_session, stage):
    _, token, _ = await _open_link(db_session, stage=stage)

    assert await patient_form_service.find_open(db_session, token) is None


def test_the_feature_needs_all_three_flags(monkeypatch):
    for flag in (
        "agentic_pipeline_enabled",
        "email_booking_conversation_enabled",
        "patient_form_link_enabled",
    ):
        monkeypatch.setattr(settings, flag, True)
    assert patient_form_service.enabled()
    monkeypatch.setattr(settings, "email_booking_conversation_enabled", False)
    assert not patient_form_service.enabled()


def test_the_link_email_asks_for_nothing_by_email():
    text = patient_form_service.link_text("https://app.clinic.example/register/abc")

    assert "https://app.clinic.example/register/abc" in text
    assert "7 days" in text
    for never in ("medicare", "medication", "payment", "insurance", "[", "you must"):
        assert never not in text.lower()
