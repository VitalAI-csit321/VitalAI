from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import VIEW_CLINICAL
from app.auth.scoping import allowed_scopes, can_read_clinical, is_assigned
from app.models.assignment import DoctorPatientAssignment
from app.models.patient import Gender, Patient, PatientStatus
from app.models.permission_grant import UserPermissionGrant
from app.models.user import User, UserRole


def _user(role: UserRole, granted: list[str] | None = None) -> User:
    user = User(
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        hashed_password="h",
        full_name="X",
        role=role,
    )
    user.permission_grants = [
        UserPermissionGrant(user_id=user.id, permission=p, granted_by=user.id)
        for p in (granted or [])
    ]
    return user


async def _patient(db_session: AsyncSession) -> Patient:
    p = Patient(
        mrn=f"MRN-{uuid4().hex[:8].upper()}",
        name="Scoping Test Patient",
        dob=date(1990, 1, 1),
        gender=Gender.MALE,
        status=PatientStatus.ACTIVE,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def test_is_assigned_true_after_assignment(db_session: AsyncSession):
    doctor = _user(UserRole.DOCTOR)
    db_session.add(doctor)
    await db_session.commit()
    patient = await _patient(db_session)
    db_session.add(
        DoctorPatientAssignment(doctor_id=doctor.id, patient_id=patient.id, assigned_by=doctor.id)
    )
    await db_session.commit()

    assert await is_assigned(db_session, doctor.id, patient.id) is True


async def test_is_assigned_false_without_assignment(db_session: AsyncSession):
    doctor = _user(UserRole.DOCTOR)
    db_session.add(doctor)
    await db_session.commit()
    patient = await _patient(db_session)

    assert await is_assigned(db_session, doctor.id, patient.id) is False


async def test_can_read_clinical_false_without_view_clinical_permission(db_session: AsyncSession):
    user = _user(UserRole.FRONT_DESK)
    db_session.add(user)
    await db_session.commit()
    patient = await _patient(db_session)

    assert await can_read_clinical(db_session, user, patient.id) is False


async def test_can_read_clinical_doctor_requires_assignment(db_session: AsyncSession):
    doctor = _user(UserRole.DOCTOR)
    db_session.add(doctor)
    await db_session.commit()
    patient = await _patient(db_session)

    assert await can_read_clinical(db_session, doctor, patient.id) is False

    db_session.add(
        DoctorPatientAssignment(doctor_id=doctor.id, patient_id=patient.id, assigned_by=doctor.id)
    )
    await db_session.commit()

    assert await can_read_clinical(db_session, doctor, patient.id) is True


async def test_can_read_clinical_granted_operator_is_unscoped(db_session: AsyncSession):
    # Grant is added after the user is persisted, so granted_by has a real
    # user.id to reference: user.id is only populated at flush time, not at
    # construction, unlike _user()'s pattern in test_permissions.py (which
    # never persists, so the unset id never surfaces there).
    operator = _user(UserRole.OPERATOR)
    db_session.add(operator)
    await db_session.commit()
    await db_session.refresh(operator)
    db_session.add(
        UserPermissionGrant(user_id=operator.id, permission=VIEW_CLINICAL, granted_by=operator.id)
    )
    await db_session.commit()
    # The already-loaded `operator` object's permission_grants (selectin,
    # loaded empty on first fetch) won't see the grant just added above
    # without expiring it first, the same stale-identity-map shape flagged
    # during Phase 1 (see project memory).
    await db_session.refresh(operator, attribute_names=["permission_grants"])
    patient = await _patient(db_session)

    assert await can_read_clinical(db_session, operator, patient.id) is True


def test_allowed_scopes_excludes_restricted_without_view_clinical():
    assert allowed_scopes(_user(UserRole.FRONT_DESK)) == {"general"}


def test_allowed_scopes_includes_restricted_with_view_clinical():
    assert allowed_scopes(_user(UserRole.DOCTOR)) == {"general", "restricted"}
