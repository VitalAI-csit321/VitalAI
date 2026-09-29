"""Service identities for work no logged-in human initiated.

guarded_invoke and check_output both take `actor: User` with no default, and
every audit event attributes to a real User row. A graph resuming hours after
an approval has no session to draw one from, so it uses a seeded row.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.llm.output_guardrail import check_output
from app.models.audit import AuditEvent
from app.models.user import User, UserRole
from app.services import outlook_poller, system_actor


async def test_agent_actor_is_created_once(db_session):
    first = await system_actor.get_or_create_agent_actor(db_session)
    second = await system_actor.get_or_create_agent_actor(db_session)

    assert first.id == second.id
    count = await db_session.execute(
        select(func.count()).select_from(User).where(User.email == system_actor.AGENT_EMAIL)
    )
    assert count.scalar() == 1


async def test_agent_actor_is_an_operator_and_cannot_be_logged_into(db_session):
    """Role is audit attribution only -- check_output and guarded_invoke pass
    actor straight to record_event and never read actor.role. Anything the
    agent must not read is refused in the service layer instead."""
    actor = await system_actor.get_or_create_agent_actor(db_session)

    assert actor.role == UserRole.OPERATOR
    assert actor.is_active is True
    # Random password, never stored anywhere, so there is nothing to log in with.
    assert actor.hashed_password


async def test_agent_actor_satisfies_the_guardrail_choke_points(db_session):
    """The point of the row: an existing guardrail accepts it unchanged, with
    no signature change to check_output."""
    actor = await system_actor.get_or_create_agent_actor(db_session)

    from app.llm.output_guardrail import OutputBlockedError

    with pytest.raises(OutputBlockedError):
        await check_output(
            db_session, "the patient's diagnosis is confirmed", actor=actor, case_id=None
        )

    # Scoped to this actor, not counted globally: the dev database these
    # tests share already holds committed governance.output_blocked rows from
    # earlier runs, and db_session's rollback cannot remove those.
    events = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "governance.output_blocked",
            AuditEvent.actor_id == actor.id,
        )
    )
    recorded = events.scalars().all()
    assert len(recorded) == 1


async def test_connector_actor_is_a_separate_row(db_session):
    """Two service identities, not one: the poller's ingests and the agent's
    actions have to be distinguishable in the audit trail."""
    agent = await system_actor.get_or_create_agent_actor(db_session)
    connector = await outlook_poller.get_or_create_connector_actor(db_session)

    assert agent.id != connector.id
    assert connector.role == UserRole.ADMIN


async def test_a_new_agent_actor_is_granted_view_clinical_once(db_session, admin_user, monkeypatch):
    # Without it every prescription email crashed the branch in any database
    # the seed script never ran against (black-box run, B4). Granted once, at
    # creation, by the first admin: a later revoke must stay revoked.
    from app.auth.permissions import VIEW_CLINICAL
    from app.models.permission_grant import UserPermissionGrant

    # A fresh identity: on the shared Postgres test database an earlier test
    # has usually created the real agent account already.
    monkeypatch.setattr(system_actor, "AGENT_EMAIL", f"agent-{uuid4()}@system.vitalai.internal")
    agent = await system_actor.get_or_create_agent_actor(db_session)

    grant = await db_session.get(UserPermissionGrant, (agent.id, VIEW_CLINICAL))
    # The earliest admin, which on the shared Postgres test database may be
    # one an earlier test left behind rather than this fixture's.
    assert grant is not None
    assert (await db_session.get(User, grant.granted_by)).role == UserRole.ADMIN

    await db_session.delete(grant)
    await db_session.commit()
    await system_actor.get_or_create_agent_actor(db_session)

    assert await db_session.get(UserPermissionGrant, (agent.id, VIEW_CLINICAL)) is None
