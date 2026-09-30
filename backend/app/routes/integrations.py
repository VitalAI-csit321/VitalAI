"""Clinic mailbox status and "Sign in with Microsoft" from Settings, Integrations."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import CONFIGURE_GOVERNANCE
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import audit_service, outlook_auth, outlook_poller
from app.services.outlook_auth import OutlookAuthRequiredError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/outlook", tags=["integrations"])


class MailboxStatus(BaseModel):
    enabled: bool
    account: str | None
    needs_signin: bool
    last_checked_at: datetime | None


class SignInStart(BaseModel):
    auth_url: str


@router.get("", response_model=MailboxStatus)
async def mailbox_status(_: User = Depends(require_permission(CONFIGURE_GOVERNANCE))):
    account = outlook_auth.connected_account()
    seen = outlook_poller.status
    return MailboxStatus(
        enabled=settings.outlook_enabled,
        account=account,
        needs_signin=settings.outlook_enabled and (seen.needs_signin or account is None),
        last_checked_at=seen.last_ok_at,
    )


@router.post("/connect", response_model=SignInStart)
async def start_sign_in(
    request: Request, actor: User = Depends(require_permission(CONFIGURE_GOVERNANCE))
):
    if not settings.outlook_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email isn't enabled on this installation")
    # ponytail: the redirect URI is built from the request's own host, which is
    # right when the browser reaches the API directly. Behind a proxy that
    # rewrites the host, add a configured public base URL.
    redirect_uri = str(request.url_for("outlook_callback"))
    return SignInStart(auth_url=outlook_auth.start_sign_in(redirect_uri, actor.id))


@router.get("/callback", name="outlook_callback", include_in_schema=False)
async def finish_sign_in(request: Request, db: AsyncSession = Depends(get_db)):
    """Microsoft redirects the browser here, so there is no bearer token: the
    single-use OAuth state issued by /connect is what ties it to an admin."""
    back = f"{settings.cors_origins_list[0]}/settings?section=integrations&mailbox="
    try:
        user_id, mailbox = outlook_auth.finish_sign_in(dict(request.query_params))
    except OutlookAuthRequiredError as exc:
        logger.warning("Outlook sign-in from Settings did not complete: %s", exc)
        return RedirectResponse(back + "error", status_code=status.HTTP_303_SEE_OTHER)
    outlook_poller.status.needs_signin = False
    actor = await db.get(User, user_id)
    await audit_service.record_event(
        db, action="integrations.outlook_connected", actor=actor, details={"mailbox": mailbox}
    )
    await db.commit()
    return RedirectResponse(back + "connected", status_code=status.HTTP_303_SEE_OTHER)
