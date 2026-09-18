"""Row-level scoping helpers (RBAC report §6-7).

One shared implementation per check, reused by every call site, the report
explicitly warns against inlining these per endpoint, since that's how a
boundary check silently drifts out of sync (see app/rag/retrieval.py's
_security_filter for the same principle applied to chunk retrieval).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import UPLOAD_CLINICAL, VIEW_CLINICAL, effective_permissions
from app.models.assignment import DoctorPatientAssignment
from app.models.user import User, UserRole


async def is_assigned(db: AsyncSession, doctor_id: UUID, patient_id: UUID) -> bool:
    result = await db.execute(
        select(DoctorPatientAssignment.doctor_id).where(
            DoctorPatientAssignment.doctor_id == doctor_id,
            DoctorPatientAssignment.patient_id == patient_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def can_read_clinical(db: AsyncSession, user: User, patient_id: UUID) -> bool:
    if VIEW_CLINICAL not in effective_permissions(user):
        return False
    if user.role == UserRole.DOCTOR:
        return await is_assigned(db, user.id, patient_id)
    return True


# Metadata-only visibility (filename, doc_type - never extracted_text/storage_key,
# see ClinicalDocumentOut): operators/admins can see what exists via their
# UPLOAD_CLINICAL permission even without a VIEW_CLINICAL grant, they just can't
# open the content (can_read_clinical, above, still gates GET .../file). Doctors
# are unaffected here - VIEW_CLINICAL is already their default permission - but
# still scoped to their assigned patients.
async def can_list_clinical(db: AsyncSession, user: User, patient_id: UUID) -> bool:
    perms = effective_permissions(user)
    if user.role == UserRole.DOCTOR:
        return VIEW_CLINICAL in perms and await is_assigned(db, user.id, patient_id)
    return VIEW_CLINICAL in perms or UPLOAD_CLINICAL in perms


def allowed_scopes(user: User) -> set[str]:
    scopes = {"general"}
    if VIEW_CLINICAL in effective_permissions(user):
        scopes.add("restricted")
    return scopes


def assigned_patient_ids_subquery(doctor_id: UUID) -> Select:
    return select(DoctorPatientAssignment.patient_id).where(
        DoctorPatientAssignment.doctor_id == doctor_id
    )
