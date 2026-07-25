"""Doctor-suggestion heuristic for the zero-assigned-doctor fallback
(FR-GOV-01/FR-TASK-02), see
docs/superpowers/specs/2026-07-25-governance-follow-ups-design.md section 1.

Deterministic, no LLM call: least-loaded doctor by current assignment count.
A future agent-backed suggestion can replace this function's body without
changing its signature or any caller, since the interface is just "produces
a suggested doctor id (or None)," see the design doc's "why pure functions
now, agent later" reasoning.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import DoctorPatientAssignment
from app.models.user import User, UserRole


async def suggest_doctor_for_patient(db: AsyncSession, patient_id: UUID) -> UUID | None:
    """Suggest the doctor with the fewest current patient assignments.

    Only ever a suggestion: nothing here writes an assignment. A human must
    approve the resulting ApprovalRequest before assignment_service.assign_patient()
    creates the real DoctorPatientAssignment row.
    """
    counts = (
        select(
            DoctorPatientAssignment.doctor_id,
            func.count(DoctorPatientAssignment.patient_id).label("assignment_count"),
        )
        .group_by(DoctorPatientAssignment.doctor_id)
        .subquery()
    )
    result = await db.execute(
        select(User.id)
        .outerjoin(counts, User.id == counts.c.doctor_id)
        .where(User.role == UserRole.DOCTOR)
        .order_by(func.coalesce(counts.c.assignment_count, 0).asc(), User.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
