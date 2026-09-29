from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import _deny, require_any_permission
from app.auth.permissions import VIEW_CLINICAL, VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.inbox import InboxListResponse, InboxMessageOut, WriteReplyBody
from app.services import inbox_service
from app.services.email_service import EmailSendError
from app.services.outlook_auth import OutlookAuthRequiredError

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("", response_model=InboxListResponse)
async def list_inbox_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    items, total = await inbox_service.list_inbox(
        db, actor, limit=limit, offset=offset, archived=archived
    )
    return InboxListResponse(items=items, total=total)


@router.get("/{task_id}", response_model=InboxMessageOut)
async def get_inbox_message_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    """One message: the inbox's own, or one a review item links the actor to."""
    message = await inbox_service.get_message(db, actor, task_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return message


@router.post("/{task_id}/reply", response_model=InboxMessageOut)
async def write_reply_endpoint(
    task_id: UUID,
    payload: WriteReplyBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(VIEW_QUEUE, VIEW_CLINICAL)),
):
    """Write reply (review queue spec D14): a person's own answer, sent as written."""
    task = await inbox_service.openable_task(db, actor, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if not await inbox_service.can_act_on_task(db, actor, task):
        await _deny(
            db,
            actor,
            kind="inbox_task",
            details={"task_id": str(task_id)},
            detail="This message is not yours to answer",
        )
    try:
        return await inbox_service.write_reply(db, actor, task, payload.text)
    except inbox_service.WriteReplyClosedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EmailSendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except OutlookAuthRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
