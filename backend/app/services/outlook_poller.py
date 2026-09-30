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
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services import outlook_sync_service
from app.services.outlook_auth import OutlookAuthRequiredError
from app.services.system_actor import get_or_create_system_actor

logger = logging.getLogger(__name__)


@dataclass
class PollerStatus:
    """What the last poll actually saw, for Operations and Settings."""

    last_ok_at: datetime | None = None
    needs_signin: bool = False
    failing: bool = False


status = PollerStatus()

CONNECTOR_EMAIL = "outlook-connector@vitalai.local"
CONNECTOR_NAME = "Outlook Connector"


async def get_or_create_connector_actor(db: AsyncSession) -> User:
    """The service identity the poller attributes ingested mail to.

    role=ADMIN so the classifier's guardrail and any RAG scoping downstream are
    not artificially narrowed; this actor represents the system, not a
    department. A separate row from the agent's actor, so poller ingests and
    agent actions stay distinguishable in the audit trail.
    """
    return await get_or_create_system_actor(db, CONNECTOR_EMAIL, CONNECTOR_NAME, UserRole.ADMIN)


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
            status.last_ok_at, status.needs_signin, status.failing = datetime.now(UTC), False, False
        except OutlookAuthRequiredError as exc:
            status.needs_signin = True
            logger.warning("Outlook connector needs re-authentication: %s", exc)
        except asyncio.CancelledError:
            logger.info("Outlook poller stopping")
            raise
        except Exception:
            status.failing = True
            logger.exception("Outlook poll cycle failed")
        await asyncio.sleep(settings.outlook_poll_interval_seconds)
