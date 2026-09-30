"""The close nudge (M4 spec, E5): a quiet case is put to its doctor to close.

Hourly, idempotent, always on. Not tied to appointment_reminders_enabled: it
emails nobody, it only opens Review Queue items. A case qualifies when it is
open, has had no activity for settings.case_close_nudge_days, has no upcoming
appointment, is not snoozed (Keep open) and has no open "Close this case?"
item already.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskPriority, TaskStatus, TaskType
from app.models.user import User, UserRole
from app.services import booking_service, review_routing
from app.services.audit_service import record_event
from app.services.system_actor import get_or_create_agent_actor

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
REASON = "Close this case? Nothing has happened on it for {days} days and nothing is booked."
# Appointments that still mean the case is live.
_UPCOMING = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


async def nudge_due(db: AsyncSession, actor: User) -> list[HumanReviewTask]:
    """Open one case_close item per qualifying case, and commit."""
    now = datetime.now(UTC)
    days = settings.case_close_nudge_days
    upcoming = exists().where(
        Appointment.episode_id == Episode.id,
        Appointment.time_slot > now,
        Appointment.status.in_(_UPCOMING),
    )
    already_asked = exists().where(
        HumanReviewTask.episode_id == Episode.id,
        HumanReviewTask.task_type == TaskType.CASE_CLOSE,
        HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
    )
    due = (
        await db.scalars(
            select(Episode).where(
                Episode.status == EpisodeStatus.OPEN,
                Episode.last_activity_at < now - timedelta(days=days),
                or_(Episode.nudge_snoozed_until.is_(None), Episode.nudge_snoozed_until <= now),
                ~upcoming,
                ~already_asked,
            )
        )
    ).all()
    opened = []
    for episode in due:
        doctor = await booking_service.doctor_for_episode(db, episode)
        role, owner = (UserRole.DOCTOR, doctor[0]) if doctor else (UserRole.OPERATOR, None)
        item = HumanReviewTask(
            case_id=None,
            episode_id=episode.id,
            task_type=TaskType.CASE_CLOSE,
            status=TaskStatus.PENDING,
            target_role=role,
            assigned_to=owner,
            priority=TaskPriority.LOW,
            notes=REASON.format(days=days),
        )
        db.add(item)
        await db.flush()
        await record_event(
            db,
            actor=actor,
            action="review.opened",
            details={
                "review_id": str(item.id),
                "kind": TaskType.CASE_CLOSE.value,
                "target_role": role.value,
                "episode_id": str(episode.id),
            },
        )
        opened.append(item)
    # ponytail: one commit for the sweep; a clash with a second app instance
    # (uq_human_review_open_per_episode) fails this cycle and the next hour
    # retries. Per-case savepoints if the app ever runs several instances.
    await db.commit()
    return opened


async def nudge_once() -> None:
    async with AsyncSessionLocal() as db:
        actor = await get_or_create_agent_actor(db)
        opened = await nudge_due(db, actor)
        if opened:
            logger.info("Asked about closing %d quiet case(s)", len(opened))


async def run_case_nudges() -> None:
    """Sweep until cancelled. One bad cycle must not kill the loop (same
    policy as the reminder and purge sweeps)."""
    logger.info("Case close nudge started, interval=%ds", INTERVAL_SECONDS)
    while True:
        try:
            await nudge_once()
        except asyncio.CancelledError:
            logger.info("Case close nudge stopping")
            raise
        except Exception:
            logger.exception("Case close nudge cycle failed")
        await asyncio.sleep(INTERVAL_SECONDS)
