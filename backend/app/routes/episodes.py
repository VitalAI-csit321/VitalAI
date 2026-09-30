"""Cases: episodes of care (M4 spec section 5). The UI's "case"; the older
per-message IntakeCase is a "contact" and stays under /intake.

Reading is for everyone who reads patient records, a doctor only their
assigned patients' cases (404 otherwise, as /patients does). Changing a case
is for staff who register patients and for clinicians, again a doctor only on
their own patients.
"""

from collections.abc import Awaitable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission, require_permission
from app.auth.permissions import REGISTER_PATIENT, VIEW_CLINICAL, VIEW_RECORDS_GENERAL
from app.auth.scoping import assigned_patient_ids_subquery, is_assigned
from app.database import get_db
from app.models.episode import Episode, EpisodeStatus
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.schemas.case import IntakeCaseOut
from app.schemas.episode import (
    EpisodeCloseBody,
    EpisodeCreate,
    EpisodeDetailOut,
    EpisodeListResponse,
    EpisodeMoveBody,
    EpisodeOut,
    EpisodeUpdate,
    StaffContactBody,
    TimelineEntry,
)
from app.services import episode_service

router = APIRouter(prefix="/cases", tags=["cases"])

_manage = require_any_permission(REGISTER_PATIENT, VIEW_CLINICAL)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


async def _can_see_patient(db: AsyncSession, actor: User, patient_id: UUID) -> bool:
    return actor.role != UserRole.DOCTOR or await is_assigned(db, actor.id, patient_id)


async def _visible(db: AsyncSession, actor: User, episode_id: UUID) -> Episode:
    episode = await db.get(Episode, episode_id)
    if episode is None or not await _can_see_patient(db, actor, episode.patient_id):
        raise _not_found()
    return episode


async def _outs(db: AsyncSession, episodes: list[Episode]) -> list[EpisodeOut]:
    names: dict[UUID, str] = dict(
        (
            await db.execute(
                select(Patient.id, Patient.name).where(
                    Patient.id.in_({e.patient_id for e in episodes})
                )
            )
        )
        .tuples()
        .all()
    )
    doctors: dict[UUID, str] = dict(
        (
            await db.execute(
                select(User.id, User.full_name).where(
                    User.id.in_({e.doctor_id for e in episodes if e.doctor_id})
                )
            )
        )
        .tuples()
        .all()
    )
    return [
        EpisodeOut.model_validate(e).model_copy(
            update={
                "patient_name": names.get(e.patient_id),
                "doctor_name": doctors.get(e.doctor_id) if e.doctor_id else None,
            }
        )
        for e in episodes
    ]


async def _out(db: AsyncSession, episode: Episode) -> EpisodeOut:
    return (await _outs(db, [episode]))[0]


async def _commit_or_raise[T](db: AsyncSession, action: Awaitable[T]) -> T:
    """Run a service action and commit it, mapping its refusals to HTTP."""
    try:
        result = await action
    except episode_service.EpisodeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except episode_service.WrongPatientError as exc:
        # The refusal is audited (episode_service.move); keep that event.
        await db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except episode_service.EpisodeClosedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except episode_service.EpisodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    await db.commit()
    return result


@router.get("", response_model=EpisodeListResponse)
async def list_cases_endpoint(
    patient_id: UUID | None = None,
    status_filter: EpisodeStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    filters = []
    if patient_id is not None:
        filters.append(Episode.patient_id == patient_id)
    if status_filter is not None:
        filters.append(Episode.status == status_filter)
    if actor.role == UserRole.DOCTOR:
        filters.append(Episode.patient_id.in_(assigned_patient_ids_subquery(actor.id)))
    total = await db.scalar(select(func.count()).select_from(Episode).where(*filters))
    episodes = (
        await db.scalars(
            select(Episode)
            .where(*filters)
            # Open cases first, then the most recently active.
            .order_by(
                case((Episode.status == EpisodeStatus.OPEN, 0), else_=1),
                Episode.last_activity_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return EpisodeListResponse(items=await _outs(db, list(episodes)), total=total or 0)


@router.post("", response_model=EpisodeOut, status_code=status.HTTP_201_CREATED)
async def create_case_endpoint(
    payload: EpisodeCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(_manage),
):
    if await db.get(Patient, payload.patient_id) is None or not await _can_see_patient(
        db, actor, payload.patient_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    episode = await _commit_or_raise(
        db,
        episode_service.create(
            db,
            patient_id=payload.patient_id,
            title=payload.title,
            doctor_id=payload.doctor_id,
            actor=actor,
        ),
    )
    return await _out(db, episode)


@router.get("/{episode_id}", response_model=EpisodeDetailOut)
async def get_case_endpoint(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_RECORDS_GENERAL)),
):
    episode = await _visible(db, actor, episode_id)
    entries = [TimelineEntry(**e) for e in await episode_service.timeline(db, episode)]
    return EpisodeDetailOut(**(await _out(db, episode)).model_dump(), timeline=entries)


@router.patch("/{episode_id}", response_model=EpisodeOut)
async def update_case_endpoint(
    episode_id: UUID,
    payload: EpisodeUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(_manage),
):
    episode = await _visible(db, actor, episode_id)

    async def _update() -> None:
        if payload.title is not None:
            await episode_service.rename(db, episode, payload.title, actor=actor)
        if payload.doctor_id is not None:
            await episode_service.set_doctor(db, episode, payload.doctor_id, actor=actor)

    await _commit_or_raise(db, _update())
    return await _out(db, episode)


@router.post("/{episode_id}/close", response_model=EpisodeOut)
async def close_case_endpoint(
    episode_id: UUID,
    payload: EpisodeCloseBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(_manage),
):
    episode = await _visible(db, actor, episode_id)
    await _commit_or_raise(db, episode_service.close(db, episode, note=payload.note, actor=actor))
    return await _out(db, episode)


@router.post("/{episode_id}/reopen", response_model=EpisodeOut)
async def reopen_case_endpoint(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(_manage),
):
    episode = await _visible(db, actor, episode_id)
    await _commit_or_raise(db, episode_service.reopen(db, episode, actor=actor))
    return await _out(db, episode)


@router.post("/{episode_id}/contact", response_model=IntakeCaseOut)
async def staff_contact_endpoint(
    episode_id: UUID,
    payload: StaffContactBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(_manage),
):
    """The contact a staff booking or consent for this case files under."""
    episode = await _visible(db, actor, episode_id)
    return await _commit_or_raise(
        db, episode_service.staff_contact(db, episode, reason=payload.reason, actor=actor)
    )


@router.post("/move", response_model=EpisodeOut)
async def move_endpoint(
    payload: EpisodeMoveBody,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(_manage),
):
    """Put a contact, appointment or consent in another case of the same
    patient, or a new one; for an unconfirmed contact, confirm the patient too."""
    try:
        _, contact = await episode_service.item_contact(db, payload.kind, payload.item_id)
    except episode_service.EpisodeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    patient_id = contact.patient_id or payload.patient_id
    if patient_id is not None and not await _can_see_patient(db, actor, patient_id):
        raise _not_found()
    episode = await _commit_or_raise(
        db,
        episode_service.move(
            db,
            kind=payload.kind,
            item_id=payload.item_id,
            target=payload.target_episode_id,
            new_title=payload.new_title,
            patient_id=payload.patient_id,
            actor=actor,
        ),
    )
    return await _out(db, episode)
