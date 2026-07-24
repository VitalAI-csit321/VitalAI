from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Call, CallStatus
from app.models.case import IntakeCase
from app.models.user import User
from app.schemas.call import CallCreate
from app.services.audit_service import record_event


class CaseNotFoundError(Exception):
    """Raised when a call references an intake case that does not exist."""


async def create_call(db: AsyncSession, payload: CallCreate, actor: User) -> Call:
    case = await db.get(IntakeCase, payload.case_id)
    if case is None:
        raise CaseNotFoundError(f"Case {payload.case_id} not found")

    call = Call(
        case_id=payload.case_id,
        phone_number=payload.phone_number,
        transcript=payload.transcript,
        status=CallStatus.RECEIVED,
    )
    db.add(call)
    await db.flush()

    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="call.created",
        details={"call_id": str(call.id), "manual_entry": True},
    )
    await db.commit()
    await db.refresh(call)
    return call


async def get_call(db: AsyncSession, call_id: UUID) -> Call | None:
    return await db.get(Call, call_id)


async def list_calls(db: AsyncSession) -> list[Call]:
    result = await db.execute(select(Call).order_by(Call.created_at.desc()))
    return list(result.scalars().all())
