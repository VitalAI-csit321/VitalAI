"""Cases as episodes of care (M4 spec, 2026-09-29). Every Episode write is here.

A case is one clinical problem for one patient. Its contacts (IntakeCase rows:
one per email, call or voicemail), appointments and consents point at it
through episode_id. attach_contact is the E4 rule every identity point calls
once a contact has a real patient; the rest are staff actions.

Flushes, never commits: the caller's commit keeps the case change and the
thing that caused it together, as review_routing does.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm
from app.llm.guardrail import guarded_invoke
from app.models.appointment import Appointment
from app.models.assignment import DoctorPatientAssignment
from app.models.call import Call
from app.models.case import IntakeCase, IntakeStatus
from app.models.consent import ConsentRecord
from app.models.email import Email
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.patient import Patient
from app.models.task import Task, TaskCategory
from app.models.user import User, UserRole
from app.services import booking_service, review_routing
from app.services.audit_service import record_event
from app.services.task_routing_rules import CASE_CATEGORIES

logger = logging.getLogger(__name__)

ItemKind = Literal["contact", "appointment", "consent"]

CHOICE_REASON = "Which case does this belong to? The patient has more than one open case."
# What the model reads of the message: enough to tell problems apart.
_MESSAGE_CHARS = 2000


class EpisodeError(Exception):
    """A case action the rules refuse (a missing note, a provisional patient,
    a doctor who is not one, a case that was not offered)."""


class EpisodeNotFoundError(EpisodeError):
    pass


class EpisodeClosedError(EpisodeError):
    """Closed cases take nothing new: reopen first."""


class WrongPatientError(EpisodeError):
    """The item and the case belong to different patients."""


def _now() -> datetime:
    return datetime.now(UTC)


def touch(episode: Episode) -> None:
    """Activity on the case, which is what the close nudge measures."""
    episode.last_activity_at = _now()


def category_label(category: TaskCategory) -> str:
    return category.value.replace("_", " ").capitalize()


async def _real_patient(db: AsyncSession, patient_id: UUID | None) -> Patient | None:
    """Cases are for registered patients only (E2): never provisional or purged."""
    patient = await db.get(Patient, patient_id) if patient_id is not None else None
    if patient is None or patient.is_provisional or patient.purged_at is not None:
        return None
    return patient


async def _first_task(db: AsyncSession, contact_id: UUID) -> Task | None:
    return (
        await db.execute(
            select(Task).where(Task.case_id == contact_id).order_by(Task.created_at).limit(1)
        )
    ).scalar_one_or_none()


async def _latest_task(db: AsyncSession, contact_id: UUID) -> Task | None:
    return (
        await db.execute(
            select(Task).where(Task.case_id == contact_id).order_by(Task.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def _first_email(db: AsyncSession, contact_id: UUID) -> Email | None:
    return (
        await db.execute(
            select(Email).where(Email.case_id == contact_id).order_by(Email.received_at).limit(1)
        )
    ).scalar_one_or_none()


async def _open_cases(db: AsyncSession, patient_id: UUID) -> list[Episode]:
    return list(
        (
            await db.scalars(
                select(Episode)
                .where(Episode.patient_id == patient_id, Episode.status == EpisodeStatus.OPEN)
                .order_by(Episode.last_activity_at.desc(), Episode.id)
            )
        ).all()
    )


async def get(db: AsyncSession, episode_id: UUID) -> Episode:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        raise EpisodeNotFoundError(f"No case with id {episode_id}")
    return episode


async def _audit(
    db: AsyncSession,
    actor: User | None,
    action: str,
    episode: Episode | None,
    *,
    contact_id: UUID | None = None,
    **details,
) -> None:
    await record_event(
        db,
        actor=actor,
        case_id=contact_id,
        action=action,
        details={"episode_id": str(episode.id) if episode else None, **details},
    )


async def _assign_doctor(db: AsyncSession, episode: Episode, doctor_id: UUID, actor: User) -> None:
    """The case's doctor, plus the assignment that lets them see the patient:
    doctor visibility is scoped by DoctorPatientAssignment."""
    doctor = await db.get(User, doctor_id)
    if doctor is None or doctor.role != UserRole.DOCTOR or not doctor.is_active:
        raise EpisodeError("Choose an active doctor")
    episode.doctor_id = doctor.id
    if await db.get(DoctorPatientAssignment, (doctor.id, episode.patient_id)) is None:
        db.add(
            DoctorPatientAssignment(
                doctor_id=doctor.id, patient_id=episode.patient_id, assigned_by=actor.id
            )
        )
        await db.flush()
        await record_event(
            db,
            actor=actor,
            action="assignment.created",
            details={
                "doctor_id": str(doctor.id),
                "patient_id": str(episode.patient_id),
                "reason": "case_doctor",
            },
        )
    # A pending "Close this case?" follows the case to its new doctor.
    items = await db.scalars(
        select(HumanReviewTask).where(
            HumanReviewTask.episode_id == episode.id,
            HumanReviewTask.task_type == TaskType.CASE_CLOSE,
            HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
        )
    )
    for item in items.all():
        item.target_role, item.assigned_to = UserRole.DOCTOR, doctor.id


async def create(
    db: AsyncSession,
    *,
    patient_id: UUID,
    title: str,
    actor: User,
    doctor_id: UUID | None = None,
    contact: IntakeCase | None = None,
) -> Episode:
    """A new open case. The doctor defaults to the patient's own (NULL only
    when they have none); a named doctor also gets an assignment."""
    if await _real_patient(db, patient_id) is None:
        raise EpisodeError("Cases are for registered patients only")
    title = title.strip()[:255]
    if not title:
        raise EpisodeError("A case needs a title")
    episode = Episode(
        patient_id=patient_id, title=title, status=EpisodeStatus.OPEN, opened_by=actor.id
    )
    db.add(episode)
    await db.flush()
    if doctor_id is not None:
        await _assign_doctor(db, episode, doctor_id, actor)
    else:
        doctor = await booking_service.doctor_for_patient(db, patient_id)
        episode.doctor_id = doctor[0] if doctor else None
    if contact is not None:
        contact.episode_id = episode.id
    await db.flush()
    await _audit(
        db,
        actor,
        "case.opened",
        episode,
        contact_id=contact.id if contact else None,
        patient_id=str(patient_id),
        doctor_id=str(episode.doctor_id) if episode.doctor_id else None,
    )
    return episode


async def _message_text(db: AsyncSession, contact: IntakeCase) -> str:
    email = await _first_email(db, contact.id)
    if email is not None:
        return f"Subject: {email.subject}\n\n{email.body}"[:_MESSAGE_CHARS]
    call = (
        await db.execute(select(Call).where(Call.case_id == contact.id).limit(1))
    ).scalar_one_or_none()
    return ((call.transcript if call else None) or contact.contact_reason)[:_MESSAGE_CHARS]


async def suggest(
    db: AsyncSession, contact: IntakeCase, candidates: list[Episode], actor: User
) -> Episode:
    """The model's pick among the open cases, by number. Anything else (junk,
    a number off the list, a failed or blocked call) falls back to the most
    recently active case, which candidates lists first."""
    listing = "\n".join(f"{i}. {c.title}" for i, c in enumerate(candidates, start=1))
    prompt = (
        "CASE MATCHING. A patient of the clinic sent the message below. They have these "
        "open cases:\n"
        f"{listing}\n\n"
        "Which case is the message about? Answer with the case number only.\n\n"
        f"MESSAGE:\n{await _message_text(db, contact)}\n\nCASE:"
    )
    try:
        raw = await guarded_invoke(db, get_llm(), prompt, actor=actor, route="case.suggest")
        text = raw if isinstance(raw, str) else str(getattr(raw, "content", raw))
        match = re.search(r"\d+", text)
        number = int(match.group()) if match else 0
        if 1 <= number <= len(candidates):
            return candidates[number - 1]
    except Exception:
        # A suggestion is a convenience; staff choose either way.
        logger.warning("case suggestion failed, using the most recently active case")
    return candidates[0]


async def attach_contact(
    db: AsyncSession,
    contact: IntakeCase,
    *,
    actor: User,
    category: TaskCategory | None = None,
) -> Episode | None:
    """The E4 rule. Returns the case the contact is now in, or None.

    No-op for a contact with no registered patient or a non-clinical category
    (E2, E3). A contact already in a case only marks that case active: a
    reply in a conversation is activity, not a new problem. Otherwise: no
    open case opens one, one open case takes it, several open a case_choice
    Review Queue item and leave it unattached.
    """
    if contact.episode_id is not None:
        episode = await db.get(Episode, contact.episode_id)
        if episode is not None:
            touch(episode)
        return episode
    patient = await _real_patient(db, contact.patient_id)
    if patient is None:
        return None
    if category is None:
        first = await _first_task(db, contact.id)
        category = first.category if first else None
    if category not in CASE_CATEGORIES:
        return None

    open_cases = await _open_cases(db, patient.id)
    if not open_cases:
        email = await _first_email(db, contact.id)
        assert category is not None  # checked against CASE_CATEGORIES above
        return await create(
            db,
            patient_id=patient.id,
            title=email.subject if email and email.subject.strip() else category_label(category),
            actor=actor,
            contact=contact,
        )
    if len(open_cases) == 1:
        (episode,) = open_cases
        contact.episode_id = episode.id
        touch(episode)
        await _audit(db, actor, "case.contact_attached", episode, contact_id=contact.id)
        return episode

    task = await _latest_task(db, contact.id)
    if task is None:
        # No message to hang the question on; staff attach it from the inbox.
        return None
    suggested = await suggest(db, contact, open_cases, actor)
    await review_routing.open_item(
        db,
        kind=TaskType.CASE_CHOICE,
        inbox_task=task,
        reason=CHOICE_REASON,
        actor=actor,
        details={
            "candidates": [str(c.id) for c in open_cases],
            "suggested_episode_id": str(suggested.id),
        },
    )
    return None


async def close(db: AsyncSession, episode: Episode, *, note: str, actor: User) -> None:
    note = (note or "").strip()
    if not note:
        raise EpisodeError("Closing a case needs an outcome note")
    if episode.status == EpisodeStatus.CLOSED:
        raise EpisodeClosedError("The case is already closed")
    episode.status = EpisodeStatus.CLOSED
    episode.closed_at, episode.closed_by, episode.outcome_note = _now(), actor.id, note
    # Closing settles any "Close this case?" question.
    items = await db.scalars(
        select(HumanReviewTask).where(
            HumanReviewTask.episode_id == episode.id,
            HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
        )
    )
    for item in items.all():
        item.status = TaskStatus.COMPLETED
        await record_event(
            db,
            actor=actor,
            action="review.completed",
            details={"review_id": str(item.id), "kind": item.task_type.value, "note": note},
        )
    await _audit(db, actor, "case.closed", episode, note=note)


async def reopen(db: AsyncSession, episode: Episode, *, actor: User) -> None:
    if episode.status == EpisodeStatus.OPEN:
        return
    episode.status = EpisodeStatus.OPEN
    episode.closed_at = episode.closed_by = None
    touch(episode)
    await _audit(db, actor, "case.reopened", episode)


async def rename(db: AsyncSession, episode: Episode, title: str, *, actor: User) -> None:
    title = (title or "").strip()[:255]
    if not title:
        raise EpisodeError("A case needs a title")
    previous, episode.title = episode.title, title
    await _audit(db, actor, "case.renamed", episode, previous=previous, title=title)


async def set_doctor(db: AsyncSession, episode: Episode, doctor_id: UUID, *, actor: User) -> None:
    previous = episode.doctor_id
    await _assign_doctor(db, episode, doctor_id, actor)
    await _audit(
        db,
        actor,
        "case.doctor_changed",
        episode,
        previous=str(previous) if previous else None,
        doctor_id=str(doctor_id),
    )


async def item_contact(
    db: AsyncSession, kind: ItemKind, item_id: UUID
) -> tuple[IntakeCase | Appointment | ConsentRecord, IntakeCase]:
    """The item and the contact that says whose it is."""
    item: IntakeCase | Appointment | ConsentRecord | None
    if kind == "contact":
        contact = await db.get(IntakeCase, item_id)
        item = contact
    else:
        linked: Appointment | ConsentRecord | None = (
            await db.get(Appointment, item_id)
            if kind == "appointment"
            else await db.get(ConsentRecord, item_id)
        )
        item = linked
        contact = await db.get(IntakeCase, linked.case_id) if linked is not None else None
    if item is None or contact is None:
        raise EpisodeNotFoundError(f"No {kind} with id {item_id}")
    return item, contact


async def move(
    db: AsyncSession,
    *,
    kind: ItemKind,
    item_id: UUID,
    target: UUID | None,
    actor: User,
    new_title: str | None = None,
    patient_id: UUID | None = None,
) -> Episode:
    """Put a contact, appointment or consent in another case of the same
    patient, or a new one (target None). A contact nobody has confirmed yet
    (a voicemail) takes patient_id: staff saying who it is.

    A cross-patient move is refused and audited. The refusal event is only
    flushed: the caller commits it before answering, so it survives.
    """
    item, contact = await item_contact(db, kind, item_id)
    owner = contact.patient_id
    if owner is None:
        if kind != "contact" or patient_id is None:
            raise EpisodeError("Confirm who the patient is first")
        if await _real_patient(db, patient_id) is None:
            raise EpisodeError("Cases are for registered patients only")
    elif patient_id is not None and patient_id != owner:
        raise WrongPatientError("This contact already belongs to another patient")
    patient = owner or patient_id
    assert patient is not None

    if target is None:
        destination = None
    else:
        destination = await get(db, target)
        if destination.patient_id != patient:
            await _audit(
                db,
                actor,
                "case.move_refused",
                destination,
                contact_id=contact.id,
                kind=kind,
                item_id=str(item_id),
                target=str(target),
            )
            raise WrongPatientError("That case belongs to another patient")
        if destination.status != EpisodeStatus.OPEN:
            raise EpisodeClosedError("That case is closed; reopen it first")

    if owner is None:
        confirmed = await db.get(Patient, patient)
        assert confirmed is not None
        contact.patient_id, contact.patient_name = confirmed.id, confirmed.name
        await record_event(
            db,
            actor=actor,
            case_id=contact.id,
            action="contact.patient_confirmed",
            details={"patient_id": str(confirmed.id)},
        )
    if destination is None:
        destination = await create(
            db, patient_id=patient, title=new_title or contact.contact_reason, actor=actor
        )
    previous = item.episode_id
    item.episode_id = destination.id
    touch(destination)
    if kind == "contact":
        # Filed by hand (the inbox chip): its "Which case?" question is answered.
        await review_routing.complete_open(
            db, case_id=contact.id, kind=TaskType.CASE_CHOICE, actor=actor, note="Filed by staff"
        )
    await _audit(
        db,
        actor,
        "case.item_moved",
        destination,
        contact_id=contact.id,
        kind=kind,
        item_id=str(item_id),
        **{"from": str(previous) if previous else None, "to": str(destination.id)},
    )
    return destination


async def staff_contact(
    db: AsyncSession, episode: Episode, *, reason: str, actor: User
) -> IntakeCase:
    """The contact a staff booking or consent hangs off (appointments and
    consents need one): the case's most recent contact, else a new "staff" one."""
    if episode.status != EpisodeStatus.OPEN:
        raise EpisodeClosedError("That case is closed; reopen it first")
    latest = (
        await db.execute(
            select(IntakeCase)
            .where(IntakeCase.episode_id == episode.id)
            .order_by(IntakeCase.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None:
        return latest
    patient = await db.get(Patient, episode.patient_id)
    assert patient is not None
    contact = IntakeCase(
        patient_id=patient.id,
        patient_name=patient.name,
        contact_reason=reason,
        contact_channel="staff",
        status=IntakeStatus.RECEIVED,
        episode_id=episode.id,
    )
    db.add(contact)
    await db.flush()
    await record_event(
        db,
        actor=actor,
        case_id=contact.id,
        action="intake.created",
        details={"channel": "staff", "episode_id": str(episode.id)},
    )
    return contact


async def choose(
    db: AsyncSession, item: HumanReviewTask, target: UUID | None, *, actor: User
) -> Episode:
    """Resolve a case_choice item: one of the offered cases, or a new one."""
    if item.task_type != TaskType.CASE_CHOICE or item.status not in review_routing.OPEN_STATUSES:
        raise EpisodeError("This item is not an open case choice")
    contact = await db.get(IntakeCase, item.case_id) if item.case_id else None
    if contact is None or contact.patient_id is None:
        raise EpisodeError("The message is gone")
    if target is not None and str(target) not in (item.details or {}).get("candidates", []):
        raise EpisodeError("Choose one of the offered cases, or a new one")
    if target is None:
        episode = await create(
            db,
            patient_id=contact.patient_id,
            title=contact.contact_reason,
            actor=actor,
            contact=contact,
        )
    else:
        episode = await get(db, target)
        if episode.status != EpisodeStatus.OPEN:
            raise EpisodeClosedError("That case is closed; reopen it first")
        contact.episode_id = episode.id
        touch(episode)
        await _audit(
            db, actor, "case.contact_attached", episode, contact_id=contact.id, chosen=True
        )
    item.status = TaskStatus.COMPLETED
    await record_event(
        db,
        actor=actor,
        case_id=contact.id,
        action="review.completed",
        details={
            "review_id": str(item.id),
            "kind": item.task_type.value,
            "episode_id": str(episode.id),
        },
    )
    return episode


async def timeline(db: AsyncSession, episode: Episode) -> list[dict]:
    """Everything in the case, newest first: its contacts (each with the inbox
    message it opens), appointments, consents and Review Queue items."""
    contacts = (
        await db.scalars(select(IntakeCase).where(IntakeCase.episode_id == episode.id))
    ).all()
    contact_ids = [c.id for c in contacts]
    entries: list[dict] = []
    for c in contacts:
        task = await _latest_task(db, c.id)
        entries.append(
            {
                "kind": "contact",
                "id": c.id,
                "at": c.created_at,
                "label": f"{c.contact_channel.capitalize()}: {c.contact_reason}",
                "status": task.status.value if task else None,
                "contact_id": c.id,
                "inbox_task_id": task.id if task else None,
            }
        )
    doctors: dict[UUID, str] = dict(
        (await db.execute(select(User.id, User.full_name).where(User.role == UserRole.DOCTOR)))
        .tuples()
        .all()
    )
    for a in (
        await db.scalars(select(Appointment).where(Appointment.episode_id == episode.id))
    ).all():
        entries.append(
            {
                "kind": "appointment",
                "id": a.id,
                "at": a.time_slot,
                "label": f"Appointment with {doctors.get(a.doctor_id, 'a doctor')}",
                "status": a.status.value,
                "contact_id": a.case_id,
            }
        )
    for r in (
        await db.scalars(select(ConsentRecord).where(ConsentRecord.episode_id == episode.id))
    ).all():
        entries.append(
            {
                "kind": "consent",
                "id": r.id,
                "at": r.created_at,
                "label": f"Consent: {r.consent_type.replace('_', ' ')}",
                "status": r.status.value,
                "contact_id": r.case_id,
            }
        )
    about_case = HumanReviewTask.episode_id == episode.id
    items = await db.scalars(
        select(HumanReviewTask).where(
            about_case | HumanReviewTask.case_id.in_(contact_ids) if contact_ids else about_case
        )
    )
    for item in items.all():
        entries.append(
            {
                "kind": "review",
                "id": item.id,
                "at": item.created_at,
                "label": item.notes or item.task_type.value.replace("_", " ").capitalize(),
                "status": item.status.value,
                "contact_id": item.case_id,
            }
        )
    # SQLite hands back naive datetimes; they are all UTC.
    return sorted(
        entries,
        key=lambda e: e["at"] if e["at"].tzinfo else e["at"].replace(tzinfo=UTC),
        reverse=True,
    )
