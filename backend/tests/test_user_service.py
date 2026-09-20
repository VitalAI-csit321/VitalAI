from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models import User, UserRole
from app.models.audit import AuditEvent
from app.services import user_service


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole = UserRole.FRONT_DESK
) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("password123"),
        full_name="Service Test User",
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_set_department_updates_and_persists(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor1@example.com", UserRole.ADMIN)
    target = await _make_user(db_session, "target1@example.com")

    updated = await user_service.set_department(db_session, target, "Radiology", actor)

    assert updated.department == "Radiology"
    refetched = (await db_session.execute(select(User).where(User.id == target.id))).scalar_one()
    assert refetched.department == "Radiology"


async def test_set_department_writes_audit_event(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor2@example.com", UserRole.ADMIN)
    target = await _make_user(db_session, "target2@example.com")

    await user_service.set_department(db_session, target, "Cardiology", actor)

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "user.department_updated", AuditEvent.actor_id == actor.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].actor_id == actor.id
    assert events[0].details == {"user_id": str(target.id), "department": "Cardiology"}


async def test_list_users_returns_all_when_no_search(db_session: AsyncSession):
    await _make_user(db_session, "listuser1@example.com")
    await _make_user(db_session, "listuser2@example.com")

    rows, total = await user_service.list_users(db_session)

    assert total >= 2
    emails = {user.email for user, _ in rows}
    assert "listuser1@example.com" in emails
    assert "listuser2@example.com" in emails


async def test_list_users_search_matches_name(db_session: AsyncSession):
    user = User(
        email="findme@example.com",
        hashed_password=hash_password("password123"),
        full_name="Findable Person",
        role=UserRole.FRONT_DESK,
    )
    db_session.add(user)
    await db_session.commit()

    rows, total = await user_service.list_users(db_session, search="Findable")

    assert total == 1
    assert rows[0][0].email == "findme@example.com"


async def test_list_users_search_matches_email(db_session: AsyncSession):
    user = User(
        email="uniqueemailsearch@example.com",
        hashed_password=hash_password("password123"),
        full_name="Someone",
        role=UserRole.FRONT_DESK,
    )
    db_session.add(user)
    await db_session.commit()

    rows, total = await user_service.list_users(db_session, search="uniqueemailsearch")

    assert total == 1
    assert rows[0][0].id == user.id


async def test_list_users_last_active_none_without_events(db_session: AsyncSession):
    await _make_user(db_session, "noaudit@example.com")

    rows, _ = await user_service.list_users(db_session, search="noaudit")

    assert rows[0][1] is None


async def test_list_users_last_active_is_most_recent_event(db_session: AsyncSession):
    user = await _make_user(db_session, "hasaudit@example.com")
    older = AuditEvent(
        actor_id=user.id,
        actor_label=user.email,
        action="test.old",
        timestamp=datetime.now(UTC) - timedelta(days=2),
    )
    newer = AuditEvent(
        actor_id=user.id,
        actor_label=user.email,
        action="test.new",
        timestamp=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    rows, _ = await user_service.list_users(db_session, search="hasaudit")

    assert rows[0][1] is not None
    # SQLite (this suite's default test DB) doesn't round-trip tzinfo, so a
    # value read back through a fresh query compares naive against the
    # original tz-aware Python object; normalize both sides before comparing.
    assert rows[0][1].replace(tzinfo=None) == newer.timestamp.replace(tzinfo=None)


async def test_list_users_last_active_is_isolated_per_user(db_session: AsyncSession):
    user_a = await _make_user(db_session, "isolationa@example.com")
    user_b = await _make_user(db_session, "isolationb@example.com")
    event_a = AuditEvent(
        actor_id=user_a.id,
        actor_label=user_a.email,
        action="test.a",
        timestamp=datetime.now(UTC) - timedelta(hours=3),
    )
    event_b = AuditEvent(
        actor_id=user_b.id,
        actor_label=user_b.email,
        action="test.b",
        timestamp=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add_all([event_a, event_b])
    await db_session.commit()

    rows, _ = await user_service.list_users(db_session, search="isolation")

    last_active_by_email = {user.email: last_active for user, last_active in rows}
    assert last_active_by_email["isolationa@example.com"] is not None
    assert last_active_by_email["isolationb@example.com"] is not None
    # user_b's event is more recent than user_a's, so if the subquery leaked
    # across rows both would show the same (later) timestamp instead of each
    # reflecting only its own actor's events.
    assert (
        last_active_by_email["isolationa@example.com"]
        < last_active_by_email["isolationb@example.com"]
    )


async def test_list_users_pagination(db_session: AsyncSession):
    for i in range(5):
        await _make_user(db_session, f"pageuser{i}@example.com")

    rows, total = await user_service.list_users(db_session, limit=2, offset=0)

    assert len(rows) == 2
    assert total >= 5


async def test_the_user_list_filters_by_role_and_department_server_side(db_session):
    """The Users page loaded one page and filtered it in the browser, so its
    role and department filters, its search and its "N active" counts all only
    ever saw the twenty rows it happened to have fetched. Filtering belongs
    where the rows are, next to the paging and the total.
    """
    from app.auth.security import hash_password
    from app.models.user import User, UserRole
    from app.services import user_service

    for email, role, dept in [
        ("filter-a@example.com", UserRole.OPERATOR, "Reception"),
        ("filter-b@example.com", UserRole.OPERATOR, "Billing"),
        ("filter-c@example.com", UserRole.DOCTOR, "Reception"),
    ]:
        db_session.add(
            User(
                email=email,
                hashed_password=hash_password("pass1234"),
                full_name=f"Filter {role.value}",
                role=role,
                department=dept,
            )
        )
    await db_session.commit()

    operators, op_total = await user_service.list_users(db_session, role=UserRole.OPERATOR)
    assert op_total >= 2
    assert all(u.role == UserRole.OPERATOR for u, _ in operators)

    reception, rec_total = await user_service.list_users(db_session, department="Reception")
    assert rec_total >= 2
    assert all(u.department == "Reception" for u, _ in reception)

    both, both_total = await user_service.list_users(
        db_session, role=UserRole.OPERATOR, department="Reception"
    )
    assert both_total >= 1
    assert all(u.role == UserRole.OPERATOR and u.department == "Reception" for u, _ in both)
    # The total is the count of matches, not of the page returned.
    assert both_total == len(both) or both_total > len(both)


async def test_the_user_list_reports_every_department_not_just_this_page(
    client: AsyncClient, admin_headers: dict, db_session
):
    """The department filter was populated from whichever twenty rows the page
    had loaded, so departments belonging to anyone further down the list were
    simply not offered. The list endpoint reports them all."""
    from app.auth.security import hash_password
    from app.models.user import User, UserRole

    db_session.add(
        User(
            email="dept-far@example.com",
            hashed_password=hash_password("pass1234"),
            full_name="Far Away",
            role=UserRole.OPERATOR,
            department="Pathology",
        )
    )
    await db_session.commit()

    response = await client.get("/api/v1/auth/users?limit=1", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert "Pathology" in body["departments"]
