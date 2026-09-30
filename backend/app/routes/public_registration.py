"""The registration form's two public endpoints (patient_form_service).

No login: the link in the patient's email is the credential. Every kind of
bad link gets the same 404, so a guess learns nothing. Both routes are on
the reviewed no-permission allowlist in tests/test_rbac_enforcement.py.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models.email import Email
from app.models.user import User, UserRole
from app.schemas.registration import RegistrationDoctor, RegistrationLinkOut, RegistrationSubmit
from app.services import consent_service, patient_form_service
from app.services.system_actor import get_or_create_agent_actor

router = APIRouter(prefix="/public/registration", tags=["public"])

NOT_VALID = "This link is not valid. It may have expired or already been used."


def _not_valid() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_VALID)


# One bucket per client IP for both routes. A plain limiter.limit keys on the
# URL, and every token is a different URL, so it would never stop a guesser.
_RATE_LIMIT = limiter.shared_limit(settings.public_form_rate_limit, scope="public_registration")


@router.get("/{token}", response_model=RegistrationLinkOut)
@_RATE_LIMIT
async def open_registration_link(
    request: Request, token: str, db: AsyncSession = Depends(get_db)
) -> RegistrationLinkOut:
    if not patient_form_service.enabled():
        raise _not_valid()
    conversation = await patient_form_service.find_open(db, token)
    if conversation is None:
        raise _not_valid()
    origin = await db.get(Email, conversation.origin_email_id)
    assert origin is not None  # find_open refuses a conversation whose origin email is gone
    return RegistrationLinkOut(
        email=origin.sender.strip(),
        needs_preferred_day=patient_form_service.needs_preferred_day(conversation),
        statements=list(patient_form_service.CONSENT_STATEMENTS),
        clauses=list(consent_service.CLINIC_CLAUSES),
        clinic_checks=list(consent_service.CLINIC_CHECKS),
        doctors=[
            RegistrationDoctor(id=doctor_id, name=name)
            for doctor_id, name in (
                await db.execute(
                    select(User.id, User.full_name)
                    .where(User.role == UserRole.DOCTOR, User.is_active.is_(True))
                    .order_by(User.full_name)
                )
            ).tuples()
        ],
    )


@router.post("/{token}", status_code=status.HTTP_201_CREATED)
@_RATE_LIMIT
async def submit_registration(
    request: Request,
    token: str,
    payload: RegistrationSubmit,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not patient_form_service.enabled():
        raise _not_valid()
    # Before the row lock: creating the agent account commits, which would
    # release it.
    actor = await get_or_create_agent_actor(db)
    conversation = await patient_form_service.find_open(db, token, lock=True)
    if conversation is None:
        raise _not_valid()
    try:
        patient = await patient_form_service.submit(db, conversation, payload, actor)
    except patient_form_service.RegistrationRejectedError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if patient is not None:
        background.add_task(
            patient_form_service.send_followup, conversation.id, payload.part_of_day
        )
    return {"status": "received"}
