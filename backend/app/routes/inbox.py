from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission
from app.auth.permissions import VIEW_CLINICAL, VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.inbox import InboxListResponse
from app.services import inbox_service

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("", response_model=InboxListResponse)
async def list_inbox_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    items, total = await inbox_service.list_inbox(db, actor, limit=limit, offset=offset)
    return InboxListResponse(items=items, total=total)
