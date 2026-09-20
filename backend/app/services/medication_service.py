"""Medication history, and the clinical access rule that guards it (§12.2).

**The permission check is in this module on purpose, not on a route.**
`require_permission()` is a FastAPI dependency, so it only runs for requests
that arrive over HTTP. A graph run scheduled from the poller never passes
through a route, which means a node could otherwise read any patient's
medication history with nothing at all standing in the way. That is tolerable
while agents touch case and org data; it stops being tolerable here, because
this is clinical patient data.

The precedent is `inbox_service._visible_tasks`, which checks VIEW_ALL_QUEUES
inside the service for the same reason.

VIEW_CLINICAL belongs to DOCTOR by role. The agent actor is an OPERATOR and
holds it only through an explicit, revocable grant (spec G.17), so revoking
that grant in the UI genuinely turns this off.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import VIEW_CLINICAL, effective_permissions
from app.config import settings
from app.models.medication import Medication, MedicationStatus
from app.models.user import User


class ClinicalAccessDeniedError(Exception):
    """The actor may not read clinical data.

    Deliberately not an HTTPException: this is raised on the agent path too,
    where there is no request to turn it into a response.
    """


async def get_medication_history(
    db: AsyncSession, patient_id: UUID, *, actor: User
) -> list[Medication]:
    """Every medication on record for this patient, newest prescription first.

    Raises ClinicalAccessDeniedError when the actor does not hold VIEW_CLINICAL,
    whether or not the call arrived over HTTP.
    """
    if VIEW_CLINICAL not in effective_permissions(actor):
        raise ClinicalAccessDeniedError(
            f"Actor {actor.id} does not hold '{VIEW_CLINICAL}' and may not read medication history"
        )
    rows = await db.execute(
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .order_by(Medication.prescribed_on.desc())
    )
    return list(rows.scalars().all())


def check_last_review_date(medications: list[Medication], *, today: date | None = None) -> bool:
    """Whether a review is due before anything can be renewed.

    True (a review is due) when there is nothing active to renew, or when any
    active medication has no recorded review or one older than the configured
    interval. The pessimistic reading is deliberate: "no review on record" is
    not evidence of a recent review, and a medication carried over from
    another practice has none.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=settings.medication_review_interval_days)
    active = [m for m in medications if m.status == MedicationStatus.ACTIVE]
    if not active:
        return True
    return any(m.last_review_date is None or m.last_review_date < cutoff for m in active)


def prescriber_id(medications: list[Medication]) -> UUID | None:
    """Who to send the internal request to: the prescriber of the most recent
    active medication, or None when nothing on record names one."""
    for medication in medications:
        if medication.status == MedicationStatus.ACTIVE and medication.prescribed_by_id:
            return medication.prescribed_by_id
    return None
