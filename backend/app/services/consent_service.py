from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.user import User
from app.services.audit_service import record_event


class ConsentStateError(Exception):
    """Raised when a consent state transition is illegal."""


# Consent implied by someone emailing the clinic first (build spec §9.0). It is
# recorded PENDING, never CAPTURED: CAPTURED is the only status the consent
# gate accepts, so an implied record must never satisfy it.
IMPLIED_INBOUND_CONTACT = "implied_inbound_contact"
# Given by the patient on the registration form (patient_form_service).
# Pending until staff have seen ID and verify it.
ONLINE_REGISTRATION = "online_registration"

# The clinic's own consent: what staff capture in person, and what the
# registration form shows the patient to agree to ahead of the visit. Keep in
# step with CLAUSES and CHECKS in frontend ConsentCapturePage.tsx.
CLINIC_CLAUSES = (
    (
        "I hereby consent to receive medical treatment at GreenCare Family Medical Clinic, "
        "including examination, diagnostic procedures, and treatment deemed necessary by my "
        "healthcare provider."
    ),
    (
        "I understand that no guarantees have been made concerning results of treatment and "
        "healthcare professionals will use their best judgment."
    ),
    (
        "I authorize GreenCare Family Medical Clinic to disclose my medical information as "
        "necessary for treatment, payment, and healthcare operations."
    ),
)
CLINIC_CHECKS = (
    "I have read and understood the consent form",
    "I have had the opportunity to ask questions",
    "I consent to share my records with other healthcare providers as needed",
    "I consent to be contacted for research purposes",
)


async def create_consent_record(
    db: AsyncSession,
    case_id: UUID,
    actor: User,
    consent_type: str = "administrative",
    notes: str | None = None,
    form_snapshot: dict | None = None,
) -> ConsentRecord:
    record = ConsentRecord(
        case_id=case_id,
        status=ConsentStatus.PENDING,
        consent_type=consent_type,
        notes=notes,
        form_snapshot=form_snapshot,
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


async def list_consents_for_patient(db: AsyncSession, patient_id: UUID) -> list[ConsentRecord]:
    """All consent records across every case for this patient - a reused case
    can carry more than one consent record over time, unlike
    get_consent_for_case() which only ever returns the latest per case."""
    result = await db.execute(
        select(ConsentRecord)
        .join(IntakeCase, IntakeCase.id == ConsentRecord.case_id)
        .where(IntakeCase.patient_id == patient_id)
        .order_by(ConsentRecord.created_at.desc())
    )
    return list(result.scalars().all())


async def list_consent_queue(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> tuple[list[tuple[ConsentRecord, str | None]], int]:
    """Every consent record, newest first, with the name of the patient on its
    case. One query rather than a lookup per row.

    The staff queue is built from this. It used to be built from the most
    recent intake cases instead, which meant a case with no consent record was
    shown as awaiting consent and the form name was a placeholder.
    """
    base = (
        select(ConsentRecord, IntakeCase.patient_name)
        .join(IntakeCase, IntakeCase.id == ConsentRecord.case_id)
        .order_by(ConsentRecord.created_at.desc())
    )
    total = (await db.execute(select(func.count()).select_from(ConsentRecord))).scalar_one()
    rows = (await db.execute(base.limit(limit).offset(offset))).all()
    return [(r[0], r[1]) for r in rows], total


async def capture_consent(
    db: AsyncSession, consent_id: UUID, actor: User, form_snapshot: dict | None = None
) -> ConsentRecord | None:
    record = await db.get(ConsentRecord, consent_id)
    if record is None:
        return None

    if record.status != ConsentStatus.PENDING:
        raise ConsentStateError(
            f"Cannot capture consent in state '{record.status.value}'. Must be 'pending'."
        )

    record.status = ConsentStatus.CAPTURED
    record.captured_at = datetime.now(UTC)
    record.form_snapshot = form_snapshot

    await record_event(
        db,
        case_id=record.case_id,
        actor=actor,
        action="consent.captured",
        details={"consent_id": str(consent_id)},
    )

    unchecked = [c["label"] for c in (form_snapshot or {}).get("checks", []) if not c["checked"]]
    if unchecked:
        db.add(
            HumanReviewTask(
                case_id=record.case_id,
                task_type=TaskType.CONSENT_REVIEW,
                target_role=actor.role,
                notes=f"Consent captured with unchecked items: {', '.join(unchecked)}",
            )
        )
        await record_event(
            db,
            case_id=record.case_id,
            actor=actor,
            action="consent.escalated",
            details={"consent_id": str(consent_id), "unchecked": unchecked},
        )

    await db.commit()
    await db.refresh(record)
    return record


async def verify_online_consent(
    db: AsyncSession,
    consent_id: UUID,
    actor: User,
    *,
    checks: list[bool] | None = None,
    signature: str | None = None,
) -> ConsentRecord | None:
    """Staff have seen ID: the patient's online consent becomes captured.

    The patient may have left the clinic's statements unticked or not signed;
    staff finish it with them at the clinic. `checks` answers the statements
    already on the record, in order (the wording cannot change here), and
    `signature` is taken when the record has none. A statement still unticked
    goes to review, as capture_consent does for any consent.

    capture_consent replaces the snapshot with whatever it is given, so it is
    given the existing one back, updated, plus who verified it.
    """
    record = await db.get(ConsentRecord, consent_id)
    if record is None:
        return None
    if record.consent_type != ONLINE_REGISTRATION or record.status != ConsentStatus.PENDING:
        raise ConsentStateError("Only a pending online registration consent can be verified.")
    snapshot = dict(record.form_snapshot or {})
    stored = snapshot.get("checks") or []
    if checks is not None:
        if len(checks) != len(stored):
            raise ConsentStateError("Answer each consent statement once.")
        snapshot["checks"] = [{**c, "checked": v} for c, v in zip(stored, checks, strict=True)]
    if signature:
        snapshot["signature"] = signature
    if not snapshot.get("signature"):
        raise ConsentStateError("The patient's signature is needed before this can be verified.")
    return await capture_consent(db, consent_id, actor, {**snapshot, "verified_by": str(actor.id)})


async def update_consent_checklist(
    db: AsyncSession, consent_id: UUID, actor: User, form_snapshot: dict
) -> ConsentRecord | None:
    """Let staff finish ticking a consent's checklist after it landed in
    review (some items were left unchecked at capture time). Only valid on
    an already-captured record - the initial capture uses capture_consent().
    """
    record = await db.get(ConsentRecord, consent_id)
    if record is None:
        return None

    if record.status != ConsentStatus.CAPTURED:
        raise ConsentStateError(
            f"Cannot update checklist for consent in state '{record.status.value}'. "
            "Must be 'captured'."
        )

    record.form_snapshot = form_snapshot

    await record_event(
        db,
        case_id=record.case_id,
        actor=actor,
        action="consent.checklist_updated",
        details={"consent_id": str(consent_id)},
    )

    still_unchecked = [c["label"] for c in form_snapshot.get("checks", []) if not c["checked"]]
    if not still_unchecked:
        result = await db.execute(
            select(HumanReviewTask).where(
                HumanReviewTask.case_id == record.case_id,
                HumanReviewTask.task_type == TaskType.CONSENT_REVIEW,
                HumanReviewTask.status.in_(
                    [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.ESCALATED]
                ),
            )
        )
        for task in result.scalars().all():
            task.status = TaskStatus.COMPLETED

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
