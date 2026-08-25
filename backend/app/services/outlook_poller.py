"""Background poll loop for the Outlook connector.

Matthew's original ran once from __main__ and exited. This runs the same
sequence on a timer inside the app's lifespan, which means it needs two things
a one-shot script did not: an audit actor (every recorded event in this
codebase attributes to a real User row) and a failure policy that keeps the
loop alive across transient Graph outages.
"""

from __future__ import annotations

import asyncio
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services import outlook_sync_service
from app.services.outlook_auth import OutlookAuthRequiredError

logger = logging.getLogger(__name__)

CONNECTOR_EMAIL = "outlook-connector@vitalai.local"
CONNECTOR_NAME = "Outlook Connector"


async def get_or_create_connector_actor(db: AsyncSession) -> User:
    """The service identity the poller attributes ingested mail to.

    role=ADMIN so the classifier's guardrail and any RAG scoping downstream are
    not artificially narrowed; this actor represents the system, not a
    department. The password is random and never stored anywhere, so the
    account cannot be logged into: it exists only to satisfy the audit trail's
    requirement that every event has a real actor row.
    """
    result = await db.execute(select(User).where(User.email == CONNECTOR_EMAIL))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    actor = User(
        email=CONNECTOR_EMAIL,
        full_name=CONNECTOR_NAME,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(actor)
    await db.commit()
    await db.refresh(actor)
    logger.info("Created Outlook connector service account %s", CONNECTOR_EMAIL)
    return actor


async def poll_once() -> None:
    async with AsyncSessionLocal() as db:
        actor = await get_or_create_connector_actor(db)
        summary = await outlook_sync_service.sync_inbox(db, actor)
        if summary.fetched:
            logger.info(
                "Outlook poll: fetched=%d ingested=%d duplicate=%d unparseable=%d failed=%d",
                summary.fetched,
                summary.ingested,
                summary.skipped_duplicate,
                summary.skipped_unparseable,
                summary.failed,
            )


async def run_poller() -> None:
    """Poll until cancelled.

    Every cycle is wrapped: a Graph outage, a malformed response or a database
    hiccup must not kill the loop, because nothing would restart it short of an
    app restart. OutlookAuthRequiredError is logged distinctly because it needs
    a human to re-run the login script, not a retry.
    """
    logger.info("Outlook poller started, interval=%ds", settings.outlook_poll_interval_seconds)
    while True:
        try:
            await poll_once()
        except OutlookAuthRequiredError as exc:
            logger.warning("Outlook connector needs re-authentication: %s", exc)
        except asyncio.CancelledError:
            logger.info("Outlook poller stopping")
            raise
        except Exception:
            logger.exception("Outlook poll cycle failed")
        await asyncio.sleep(settings.outlook_poll_interval_seconds)
