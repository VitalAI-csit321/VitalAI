import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.models.task import TaskCategory
from app.models.user import UserRole
from app.schemas.email import EmailIngestRequest
from app.services import email_service
from app.services.task_routing_rules import resolve_target_role


class _FakeLLM:
    """Matches tests/test_email_service.py's fixture: answers WORTHY for the
    reply-worthiness gate's separate call, and the classifier's canned
    response otherwise."""

    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


def test_routing_override_changes_the_target_role():
    original = settings.task_routing_category_roles
    try:
        settings.task_routing_category_roles = {"prescription_renewal": "operator"}
        assert resolve_target_role(TaskCategory.PRESCRIPTION_RENEWAL) == UserRole.OPERATOR
    finally:
        settings.task_routing_category_roles = original


def test_categories_without_an_override_keep_the_builtin_role():
    original = settings.task_routing_category_roles
    try:
        settings.task_routing_category_roles = {"prescription_renewal": "operator"}
        assert resolve_target_role(TaskCategory.RESULTS_ENQUIRY) == UserRole.DOCTOR
    finally:
        settings.task_routing_category_roles = original


def test_a_malformed_override_falls_back_instead_of_crashing():
    original = settings.task_routing_category_roles
    try:
        settings.task_routing_category_roles = {"prescription_renewal": "not_a_role"}
        assert resolve_target_role(TaskCategory.PRESCRIPTION_RENEWAL) == UserRole.DOCTOR
    finally:
        settings.task_routing_category_roles = original


def test_llm_params_reach_the_provider():
    from app.llm.provider import get_llm

    original = settings.llm_temperature
    try:
        get_llm.cache_clear()
        settings.llm_temperature = 0.15
        llm = get_llm()
        assert getattr(llm, "temperature", None) == 0.15
    finally:
        settings.llm_temperature = original
        get_llm.cache_clear()


@pytest.mark.asyncio
async def test_auto_send_disabled_blocks_a_reply_that_would_otherwise_send(
    db_session, front_desk_user, monkeypatch
):
    """email_auto_send_enabled=False must veto safe_to_send_immediately even when
    every other condition passes."""
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Opening hours",
        body="What time do you open on Saturdays?",
    )
    email, task, gate, confidence = await email_service.ingest_email(
        db_session, payload, front_desk_user
    )

    original = settings.email_auto_send_enabled
    try:
        settings.email_auto_send_enabled = False
        with patch(
            "app.services.email_service._generate_org_grounded_reply",
            new=AsyncMock(return_value=("We open at 9am on Saturdays.", True)),
        ):
            outcome = await email_service.draft_reply(
                db_session, task, email, front_desk_user, gate, confidence
            )
    finally:
        settings.email_auto_send_enabled = original

    assert outcome.sent is False
    assert outcome.approval_id is not None
