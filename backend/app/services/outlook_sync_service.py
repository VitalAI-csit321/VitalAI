"""Pull unread Outlook mail into the existing email pipeline.

The per-message sequence is Matthew's, from Inbox_Handling's main.py
process_email(): authenticate, fetch unread, then for each message parse it,
classify/route it, and mark it read, never letting a mark-as-read failure
abort the run. What changes is that each step delegates to this codebase's
own services (email_service.ingest_email does classification, gating and Task
creation) instead of the standalone stub components, plus two additions:
idempotent dedupe before ingestion, and draft generation after it.

Kept separate from the poll loop in app.main so that "sync the inbox once" is
directly testable without running a timer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email
from app.models.user import User
from app.schemas.email import EmailIngestRequest
from app.services import email_service, outlook_client
from app.services.audit_service import record_event
from app.services.outlook_client import EXTERNAL_SOURCE

logger = logging.getLogger(__name__)

# The poll filter is `isRead eq false`, so anything left unread comes back on
# every cycle forever. Three attempts separates a transient fault (LLM or DB
# hiccup, worth retrying) from a message this pipeline will never ingest.
# Counts live in memory only: marking the message read is the durable stop, so
# a counter merely has to survive long enough within one process to reach the
# cap, and a restart granting a few extra attempts is harmless.
MAX_INGEST_ATTEMPTS = 3
_failed_attempts: dict[str, int] = {}


@dataclass
class SyncSummary:
    fetched: int
    ingested: int
    skipped_duplicate: int
    skipped_unparseable: int
    failed: int


async def _already_ingested(db: AsyncSession, external_id: str) -> bool:
    """Dedupe against the unique index from alembic 0024_outlook_email_dedup.

    This, not mark_as_read, is the real guarantee that a message is ingested
    once: marking read is a separate Graph call that can fail independently,
    and a message left unread would otherwise come back on the next poll.
    """
    result = await db.execute(
        select(Email.id).where(
            Email.external_id == external_id,
            Email.external_source == EXTERNAL_SOURCE,
        )
    )
    return result.first() is not None


async def _process_one(
    db: AsyncSession, request: EmailIngestRequest, actor: User, access_token: str
) -> None:
    email, task, gate, confidence = await email_service.ingest_email(db, request, actor)
    await email_service.draft_reply(db, task, email, actor, gate, confidence)

    # Matthew's original guard, kept: a failed mark-as-read must not undo an
    # ingest that already committed. The dedupe check above means the message
    # is skipped next cycle regardless, so the mailbox is merely untidy, not
    # reprocessed.
    try:
        await outlook_client.mark_as_read(access_token, str(request.external_id))
    except Exception:
        logger.warning("Failed to mark Outlook message %s as read", request.external_id)


async def _give_up(
    db: AsyncSession,
    actor: User,
    access_token: str,
    message_id: str,
    action: str,
    details: dict[str, Any],
) -> None:
    """Stop refetching a message forever, and leave a trail saying why.

    Marking it read is what actually breaks the loop; the audit event is what
    reaches a human, since a message dropped silently is indistinguishable
    from one that never arrived.
    """
    try:
        await outlook_client.mark_as_read(access_token, message_id)
    except Exception:
        # Record the event regardless: the next cycle retries the mark, but
        # without this the reason a message stalled would never surface.
        logger.warning("Failed to mark abandoned message %s as read", message_id)

    await record_event(db, actor=actor, action=action, details=details)
    await db.commit()
    _failed_attempts.pop(message_id, None)


async def sync_inbox(db: AsyncSession, actor: User) -> SyncSummary:
    """Fetch unread mail and run each message through the email pipeline.

    Per-message failures are contained: one malformed or rejected message must
    not stop the rest of the batch, since the next poll would hit the same
    message again and stall the queue indefinitely.
    """
    from app.services.outlook_auth import get_access_token

    access_token = await get_access_token()
    messages = await outlook_client.get_unread_emails(access_token)

    summary = SyncSummary(
        fetched=len(messages), ingested=0, skipped_duplicate=0, skipped_unparseable=0, failed=0
    )

    for message in messages:
        request = outlook_client.to_ingest_request(message)
        if request is None:
            summary.skipped_unparseable += 1
            message_id = message.get("id")
            if message_id:
                # Unparseable is permanent, not transient: the same message
                # fails the same way on every future poll, so retrying it is
                # pure loop. A message with no id at all cannot be marked read.
                await _give_up(
                    db,
                    actor,
                    access_token,
                    str(message_id),
                    "email.ingest_unparseable",
                    {"external_id": str(message_id), "source": EXTERNAL_SOURCE},
                )
            continue

        if await _already_ingested(db, str(request.external_id)):
            summary.skipped_duplicate += 1
            # Still mark it read: it is already in the system, and leaving it
            # unread means refetching it on every future poll.
            try:
                await outlook_client.mark_as_read(access_token, str(request.external_id))
            except Exception:
                logger.warning("Failed to mark duplicate %s as read", request.external_id)
            continue

        external_id = str(request.external_id)
        try:
            await _process_one(db, request, actor, access_token)
            summary.ingested += 1
            _failed_attempts.pop(external_id, None)
        except Exception:
            logger.exception("Failed to ingest Outlook message %s", external_id)
            await db.rollback()
            # Rollback expires every instance in the session, and reading an
            # attribute off an expired one is implicit IO that async
            # SQLAlchemy cannot perform (MissingGreenlet). Without this, one
            # failed message would poison every later message in the batch,
            # defeating the per-message containment this loop exists for.
            await db.refresh(actor)
            summary.failed += 1

            attempts = _failed_attempts.get(external_id, 0) + 1
            _failed_attempts[external_id] = attempts
            if attempts >= MAX_INGEST_ATTEMPTS:
                logger.error(
                    "Abandoning Outlook message %s after %d failed attempts",
                    external_id,
                    attempts,
                )
                await _give_up(
                    db,
                    actor,
                    access_token,
                    external_id,
                    "email.ingest_abandoned",
                    {
                        "external_id": external_id,
                        "attempts": attempts,
                        "source": EXTERNAL_SOURCE,
                    },
                )

    return summary
