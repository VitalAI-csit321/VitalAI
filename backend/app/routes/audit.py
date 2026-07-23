from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.audit import AuditEventOut
from app.schemas.pagination import Page, PageParams
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])

# Kept ADMIN-only, matching the existing by-case endpoint. Worth a decision:
# if the Audit Logs page is meant to be visible to ops managers, this is the
# one line to change — but widening who can read the trail of who-accessed-
# which-patient is a governance call, not a frontend convenience, so it is
# left as-is rather than loosened to make a page render.
_audit_readers = require_roles(UserRole.ADMIN)


@router.get("", response_model=Page[AuditEventOut])
async def list_audit_endpoint(
    page: PageParams = Depends(),
    action: list[str] | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    case_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_audit_readers),
):
    """Global, filterable audit log — backs the Audit Logs & Activity page."""
    items, total = await audit_service.list_events(
        db,
        limit=page.limit,
        offset=page.offset,
        action=action,
        actor_id=actor_id,
        case_id=case_id,
        since=since,
        until=until,
    )
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(event) for event in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/actions")
async def list_audit_actions_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_audit_readers),
) -> dict[str, list[str]]:
    """Distinct action values, for the filter dropdown."""
    return {"actions": await audit_service.list_actions(db)}


@router.get("/by-case/{case_id}", response_model=list[AuditEventOut])
async def get_audit_for_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_audit_readers),
):
    return await audit_service.get_events_for_case(db, case_id)
