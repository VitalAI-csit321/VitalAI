from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import ConsentRecord, ConsentStatus
from app.models.user import User
from app.services.audit_service import record_event


class ConsentStateError(Exception):
    """Raised when a consent state transition is illegal."""


async def create_consent_record(
    db: AsyncSession,
    case_id: UUID,
    actor: User,
    consent_type: str = "administrative",
    notes: str | None = None,
) -> ConsentRecord:
    record = ConsentRecord(
        case_id=case_id,
        status=ConsentStatus.PENDING,
        consent_type=consent_type,
        notes=notes,
    )
    db.add(record)
    await db.flush()

    await record_event(
        db,
        case_id=case_id,
        actor=actor,
        action="consent.created",
        details={"consent_id": str(record.id), "type": consent_type},
    )
    await db.commit()
    await db.refresh(record)
    return record


async def get_consent_for_case(db: AsyncSession, case_id: UUID) -> ConsentRecord | None:
    result = await db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.case_id == case_id)
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def capture_consent(db: AsyncSession, consent_id: UUID, actor: User) -> ConsentRecord | None:
    record = await db.get(ConsentRecord, consent_id)
    if record is None:
        return None

    if record.status != ConsentStatus.PENDING:
        raise ConsentStateError(
            f"Cannot capture consent in state '{record.status.value}'. Must be 'pending'."
        )

    record.status = ConsentStatus.CAPTURED
    record.captured_at = datetime.now(UTC)

    await record_event(
        db,
        case_id=record.case_id,
        actor=actor,
        action="consent.captured",
        details={"consent_id": str(consent_id)},
    )
    await db.commit()
    await db.refresh(record)
    return record


async def withdraw_consent(db: AsyncSession, consent_id: UUID, actor: User) -> ConsentRecord | None:
    record = await db.get(ConsentRecord, consent_id)
    if record is None:
        return None

    if record.status not in (ConsentStatus.PENDING, ConsentStatus.CAPTURED):
        raise ConsentStateError(f"Cannot withdraw consent in state '{record.status.value}'.")

    record.status = ConsentStatus.WITHDRAWN

    await record_event(
        db,
        case_id=record.case_id,
        actor=actor,
        action="consent.withdrawn",
        details={"consent_id": str(consent_id)},
    )
    await db.commit()
    await db.refresh(record)
    return record
