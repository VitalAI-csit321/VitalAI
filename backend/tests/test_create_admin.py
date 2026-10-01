"""scripts/create_admin.py: the only way to make the first admin on a fresh box."""

import pytest
from sqlalchemy import select

from app.auth.security import verify_password
from app.models.audit import AuditEvent
from app.models.user import User, UserRole
from scripts.create_admin import run


async def test_creates_an_admin_who_can_log_in(db_session):
    user = await run(
        db_session,
        email="helen.fraser@harbourviewmedical.com.au",
        full_name="Helen Fraser",
        password="Harbourview2026",
    )

    assert user.role == UserRole.ADMIN
    assert verify_password("Harbourview2026", user.hashed_password)
    event = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == user.id))
    ).scalar_one()
    assert event.action == "user.created"
    assert event.details["via"] == "scripts.create_admin"


async def test_promotes_an_existing_account_and_keeps_its_password(db_session, front_desk_user):
    password_before = front_desk_user.hashed_password

    user = await run(
        db_session,
        email=front_desk_user.email,
        full_name=front_desk_user.full_name,
        password=None,
    )

    assert user.id == front_desk_user.id
    assert user.role == UserRole.ADMIN
    assert user.hashed_password == password_before
    event = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.action == "user.role_changed"))
    ).scalar_one()
    assert event.details["old_role"] == "front_desk"


async def test_refuses_a_short_password_and_creates_nothing(db_session):
    with pytest.raises(ValueError):
        await run(
            db_session,
            email="tom.gallagher@harbourviewmedical.com.au",
            full_name="Tom Gallagher",
            password="short",
        )

    assert (
        await db_session.scalar(
            select(User).where(User.email == "tom.gallagher@harbourviewmedical.com.au")
        )
        is None
    )
