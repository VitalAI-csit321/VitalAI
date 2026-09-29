"""The voicemail sweep (voicemail spec §10): audio retention, calls that never
got an end-of-call callback, and voicemails a restart left unprocessed.
Same shape as provisional_purge: one failed cycle never kills the loop."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.call import Call, CallKind, CallStatus
from app.services import twilio_client, voicemail_service
from app.services.audit_service import record_event
from app.storage import object_storage

logger = logging.getLogger(__name__)

STUCK_RECEIVED = timedelta(minutes=10)
STALE_LIVE_CALL = timedelta(minutes=30)


async def sweep_once(now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        actor = await voicemail_service.intake_actor(db)

        cutoff = now - timedelta(days=settings.voicemail_audio_retention_days)
        expired = (
            (
                await db.execute(
                    select(Call).where(Call.audio_key.is_not(None), Call.created_at < cutoff)
                )
            )
            .scalars()
            .all()
        )
        for call in expired:
            key = call.audio_key
            if key is None:  # the query excludes it; this narrows the type
                continue
            await asyncio.to_thread(object_storage.delete_object, key)
            call.audio_key = None
            await record_event(
                db,
                case_id=call.case_id,
                actor=actor,
                action="voicemail.audio_purged",
                details={"call_id": str(call.id)},
            )
        await db.commit()

        if settings.twilio_enabled:
            undeleted = (
                (await db.execute(select(Call).where(Call.twilio_deleted.is_(False))))
                .scalars()
                .all()
            )
            for call in undeleted:
                if call.twilio_recording_sid:
                    call.twilio_deleted = await twilio_client.delete_recording(
                        call.twilio_recording_sid
                    )
            await db.commit()

        stale = (
            (
                await db.execute(
                    select(Call).where(
                        Call.status.in_([CallStatus.IN_PROGRESS, CallStatus.RECORDING]),
                        Call.created_at < now - STALE_LIVE_CALL,
                    )
                )
            )
            .scalars()
            .all()
        )
        for call in stale:
            await voicemail_service.handle_call_ended(db, call, actor)

        # A run that died mid-processing (restart) left its claim behind.
        abandoned_claims = (
            (
                await db.execute(
                    select(Call).where(
                        Call.status == CallStatus.PROCESSING,
                        Call.updated_at < now - STALE_LIVE_CALL,
                    )
                )
            )
            .scalars()
            .all()
        )
        for call in abandoned_claims:
            call.status = CallStatus.RECEIVED
        await db.commit()
        reclaimed = [call.id for call in abandoned_claims]

        stuck = (
            (
                await db.execute(
                    select(Call.id).where(
                        Call.kind == CallKind.VOICEMAIL,
                        Call.status == CallStatus.RECEIVED,
                        Call.created_at < now - STUCK_RECEIVED,
                    )
                )
            )
            .scalars()
            .all()
        )
    for call_id in [*reclaimed, *(c for c in stuck if c not in reclaimed)]:
        await voicemail_service.process(call_id)


async def run_voicemail_sweep() -> None:
    logger.info("Voicemail sweep started, interval=%ds", settings.voicemail_sweep_interval_seconds)
    while True:
        # Sleep first: lifespan starts this on every app start (tests
        # included), and nothing here is urgent enough to need t=0.
        try:
            await asyncio.sleep(settings.voicemail_sweep_interval_seconds)
            await sweep_once()
        except asyncio.CancelledError:
            logger.info("Voicemail sweep stopping")
            raise
        except Exception:
            logger.exception("Voicemail sweep cycle failed")
