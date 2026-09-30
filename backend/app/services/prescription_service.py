"""Repeat prescription requests (build spec §12.3, as narrowed by G.16).

**The patient-facing draft names no medicine.** Not a stylistic choice: the
output guardrail's RESTRICTED_TERMS contains "prescription", "dosage
instructions", "insulin", "antibiotics", "antidepressants", "diagnosis" and
"treatment plan", and check_output runs on every graph draft. A draft naming
the medicine is blocked and discarded, so the patient would get nothing at
all. The acknowledgement therefore says only that the request is with their
doctor, or that a review is needed first. Note the word "prescription" is
itself restricted, which is why the wording is "repeat request".

The medication history is still read, through the audited VIEW_CLINICAL
grant, to decide which of the two messages applies and to find the
prescribing doctor. Reading clinical data and putting clinical data in an
email are different things: the agent does the first and never the second.

The request to the doctor is an internal Task, not mail. That keeps clinical
detail inside the system, and keeps outlook_client.send_mail at the single
caller §16 gives it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_review import TaskType
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User, UserRole
from app.services import medication_service, review_routing
from app.services.audit_service import record_event

BRANCH = "prescription"

_SIGN_OFF = "Kind regards,\nThe clinic team"
# The request Task's handover_context; the inbox and review_backfill match on these.
REVIEW_DUE_REASON = "Repeat request from the patient. A review is due before it can be renewed."
TO_CONSIDER_REASON = "Repeat request from the patient, for the prescriber to consider."
REQUEST_REASONS = (REVIEW_DUE_REASON, TO_CONSIDER_REASON)


def draft_prescription_reply(*, name: str | None, review_due: bool) -> str:
    """One of two acknowledgements. No drug name, no dose, no clinical detail.

    Nothing here invents a date, a reference or a turnaround time: "will be in
    touch" is a promise the clinic can keep.
    """
    greeting = f"Hi {name.split()[0] if name else 'there'},"
    if review_due:
        body = (
            "Thank you for your repeat request. Before we can arrange it, you are due "
            "a review with your doctor. A member of our team will be in touch to "
            "arrange a suitable time."
        )
    else:
        body = (
            "Thank you for your repeat request. It has been passed to your doctor to "
            "consider, and a member of our team will be in touch once it has been "
            "reviewed."
        )
    return f"{greeting}\n\n{body}\n\n{_SIGN_OFF}"


async def request_from_doctor(
    db: AsyncSession,
    *,
    case_id: UUID,
    patient_id: UUID,
    doctor_id: UUID | None,
    actor: User,
    review_due: bool,
) -> Task:
    """The internal half: a Task for the prescriber, never an email.

    Assigned to the prescriber when the history names one, otherwise left for
    whoever works the doctor queue, which is better than dropping it. Opens the
    matching Review Queue item in the same commit.
    """
    reason = REVIEW_DUE_REASON if review_due else TO_CONSIDER_REASON
    task = Task(
        case_id=case_id,
        assigned_to=doctor_id,
        source=TaskSource.EMAIL,
        category=TaskCategory.PRESCRIPTION_RENEWAL,
        target_role=UserRole.DOCTOR,
        priority=TaskPriority.HIGH,
        status=TaskItemStatus.PENDING,
        handover_context=reason,
    )
    db.add(task)
    await db.flush()
    await review_routing.open_item(
        db,
        kind=TaskType.PRESCRIPTION_REQUEST,
        inbox_task=task,
        reason=reason,
        actor=actor,
    )
    await record_event(
        db,
        actor=actor,
        case_id=case_id,
        action="prescription.request_raised",
        details={
            "task_id": str(task.id),
            "patient_id": str(patient_id),
            "doctor_id": str(doctor_id) if doctor_id else None,
            "review_due": review_due,
        },
    )
    await db.commit()
    return task


async def handle_renewal(db: AsyncSession, *, case_id: UUID, patient_id: UUID, actor: User) -> bool:
    """Read the history, raise the internal request, and say which reply applies.

    Returns review_due. Raises ClinicalAccessDeniedError when the actor may
    not read clinical data, which is the whole point of §12.2.
    """
    history = await medication_service.get_medication_history(db, patient_id, actor=actor)
    review_due = medication_service.check_last_review_date(history)
    await request_from_doctor(
        db,
        case_id=case_id,
        patient_id=patient_id,
        doctor_id=medication_service.prescriber_id(history),
        actor=actor,
        review_due=review_due,
    )
    return review_due
