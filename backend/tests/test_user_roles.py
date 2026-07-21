from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models import User, UserRole


def test_ops_manager_no_longer_exists():
    assert not hasattr(UserRole, "OPS_MANAGER")


def test_operator_and_doctor_are_valid_members():
    assert UserRole.OPERATOR.value == "operator"
    assert UserRole.DOCTOR.value == "doctor"


async def test_doctor_role_persists(db_session: AsyncSession):
    user = User(
        email="doctor-persist@example.com",
        hashed_password=hash_password("password123"),
        full_name="Doctor Persist Test",
        role=UserRole.DOCTOR,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.role == UserRole.DOCTOR


async def test_operator_role_persists(db_session: AsyncSession):
    user = User(
        email="operator-persist@example.com",
        hashed_password=hash_password("password123"),
        full_name="Operator Persist Test",
        role=UserRole.OPERATOR,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.role == UserRole.OPERATOR
