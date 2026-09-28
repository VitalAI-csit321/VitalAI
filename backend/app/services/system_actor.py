"""Service identities for work no logged-in human initiated.

Every audit event in this codebase attributes to a real User row, and
guarded_invoke/check_output both take `actor: User` with no default. A graph
resuming hours after an approval has no request and no session to draw an
actor from, so it uses a seeded row instead of a signature change.

Generalised from the Outlook poller's own connector account, which is the
same idea and now shares this implementation.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

AGENT_EMAIL = "agent@system.vitalai.internal"
AGENT_NAME = "VitalAI Agent"


async def get_or_create_system_actor(
    db: AsyncSession, email: str, full_name: str, role: UserRole
) -> User:
    """Fetch a service account, creating it on first use.

    The password is random and never stored anywhere, so the account cannot
    be logged into: it exists only so that events have a real actor row.
    """
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    actor = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=role,
        is_active=True,
    )
    db.add(actor)
    try:
        await db.commit()
    except IntegrityError:
        # Graph nodes each open their own session, so two of them can race
        # the very first insert. User.email is unique, so the loser re-reads
        # the winner's row rather than failing the run.
        await db.rollback()
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one()
    await db.refresh(actor)
    logger.info("Created service account %s", email)
    return actor


async def get_or_create_agent_actor(db: AsyncSession) -> User:
    """The identity the agent graph attributes its actions to.

    role=OPERATOR is audit attribution only: check_output and guarded_invoke
    pass actor straight to record_event and never read actor.role. What the
    agent may and may not touch is enforced in the service layer, which is
    where restrictions belong.

    A new account is granted VIEW_CLINICAL once, at creation, so the
    prescription branch works in a database the seed script never ran
    against. Only at creation: a revoke in the Users page must stay revoked.
    """
    existing = await db.execute(select(User).where(User.email == AGENT_EMAIL))
    agent = existing.scalar_one_or_none()
    if agent is not None:
        return agent
    agent = await get_or_create_system_actor(db, AGENT_EMAIL, AGENT_NAME, UserRole.OPERATOR)
    await _grant_clinical_at_creation(db, agent)
    return agent


async def _grant_clinical_at_creation(db: AsyncSession, agent: User) -> None:
    # Imported here: permission_service pulls in the audit layer, which
    # imports this module's callers.
    from app.auth.permissions import VIEW_CLINICAL
    from app.services import permission_service

    admin = (
        await db.execute(
            select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at).limit(1)
        )
    ).scalar_one_or_none()
    try:
        await permission_service.grant_permission(db, agent, VIEW_CLINICAL, admin or agent)
    except permission_service.DuplicateGrantError:
        # Two graph nodes raced the first creation; the other one granted it.
        await db.rollback()
