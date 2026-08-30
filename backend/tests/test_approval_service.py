import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.models.user import User, UserRole
from app.services import approval_service
from app.services.approval_service import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalNotGrantedError,
)
from tests.conftest import _PG_TEST_URL


def _user(role: UserRole) -> User:
    return User(
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        hashed_password="h",
        full_name="X",
        role=role,
    )


async def test_create_approval_request_defaults_to_pending_and_audits(db_session: AsyncSession):
    operator = _user(UserRole.OPERATOR)
    db_session.add(operator)
    await db_session.commit()

    request = await approval_service.create_approval_request(
        db_session,
        action_type="email.reply.send",
        payload={"draft": "hello"},
        requested_by=operator,
    )

    assert request.status == ApprovalStatus.PENDING
    assert request.requested_by_id == operator.id
    assert request.requested_by_label == operator.email

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "governance.approval_requested")
            )
        )
        .scalars()
        .all()
    )
    # Filtered by approval_id, not an unfiltered count: audit_events is
    # append-only (no DELETE, see 0021_block_audit_truncate), so any other
    # test that commits a real "governance.approval_requested" event against
    # this same shared Postgres instance (e.g. a cross-connection concurrency
    # test) leaves rows here permanently.
    matching = [e for e in events if e.details.get("approval_id") == str(request.id)]
    assert len(matching) == 1


async def test_create_approval_request_with_no_requester_defaults_to_system_label(
    db_session: AsyncSession,
):
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )

    assert request.requested_by_id is None
    assert request.requested_by_label == "system"


async def test_approve_transitions_status_and_audits(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )

    approved = await approval_service.approve(db_session, request.id, admin, notes="looks good")

    assert approved.status == ApprovalStatus.APPROVED
    assert approved.decided_by_id == admin.id
    assert approved.decided_at is not None
    assert approved.decision_notes == "looks good"
    assert approved.resolved_payload is None

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "governance.approval_approved")
            )
        )
        .scalars()
        .all()
    )
    # Filtered, not an unfiltered count -- see the matching comment above.
    matching = [e for e in events if e.details.get("approval_id") == str(request.id)]
    assert len(matching) == 1


async def test_approve_with_edited_payload_stores_resolved_payload(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )

    approved = await approval_service.approve(
        db_session, request.id, admin, resolved_payload={"draft": "hello, edited"}
    )

    assert approved.resolved_payload == {"draft": "hello, edited"}


async def test_reject_transitions_status_and_audits(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )

    rejected = await approval_service.reject(db_session, request.id, admin, notes="not accurate")

    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.decision_notes == "not accurate"

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "governance.approval_rejected")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


async def test_approve_missing_request_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()

    with pytest.raises(ApprovalNotFoundError):
        await approval_service.approve(db_session, uuid4(), admin)


async def test_reject_missing_request_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()

    with pytest.raises(ApprovalNotFoundError):
        await approval_service.reject(db_session, uuid4(), admin)


async def test_approve_already_decided_raises(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )
    await approval_service.approve(db_session, request.id, admin)

    with pytest.raises(ApprovalAlreadyDecidedError):
        await approval_service.approve(db_session, request.id, admin)

    with pytest.raises(ApprovalAlreadyDecidedError):
        await approval_service.reject(db_session, request.id, admin)


async def test_ensure_approved_passes_only_when_approved(db_session: AsyncSession):
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={"draft": "hello"}
    )

    with pytest.raises(ApprovalNotGrantedError):
        approval_service.ensure_approved(request)

    approved = await approval_service.approve(db_session, request.id, admin)
    approval_service.ensure_approved(approved)  # does not raise


async def test_list_approvals_filters_by_status_and_action_type(db_session: AsyncSession):
    # Suffixed with a fresh uuid: the dev/CI Postgres this suite runs against
    # also carries real approval requests from product usage, so a bare
    # "email.reply.send" would match those too, not just this test's own rows.
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    suffix = uuid4().hex[:8]
    email_type = f"email.reply.send.{suffix}"
    call_type = f"call.escalation.route.{suffix}"
    a = await approval_service.create_approval_request(
        db_session, action_type=email_type, payload={}
    )
    b = await approval_service.create_approval_request(
        db_session, action_type=call_type, payload={}
    )
    await approval_service.approve(db_session, a.id, admin)

    pending_items, pending_total = await approval_service.list_approvals(
        db_session, status=ApprovalStatus.PENDING, action_type=call_type
    )
    assert pending_total == 1
    assert pending_items[0].id == b.id

    email_items, email_total = await approval_service.list_approvals(
        db_session, action_type=email_type
    )
    assert email_total == 1
    assert email_items[0].id == a.id


async def test_list_approvals_paginates(db_session: AsyncSession):
    # Shared action_type is a fresh uuid per run so the count/pagination is
    # scoped to just these 3 rows, immune to real approval requests already
    # in the shared dev/CI Postgres.
    action_type = f"email.reply.send.{uuid4().hex[:8]}"
    for _ in range(3):
        await approval_service.create_approval_request(
            db_session, action_type=action_type, payload={}
        )

    items, total = await approval_service.list_approvals(
        db_session, action_type=action_type, limit=2, offset=0
    )
    assert total == 3
    assert len(items) == 2


async def test_get_approval_returns_none_for_missing(db_session: AsyncSession):
    assert await approval_service.get_approval(db_session, uuid4()) is None


async def test_get_approval_returns_the_request(db_session: AsyncSession):
    request = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={}
    )
    fetched = await approval_service.get_approval(db_session, request.id)
    assert fetched is not None
    assert fetched.id == request.id


async def test_approve_blocks_concurrent_decision_until_first_releases_lock():
    """Deterministic proof of approve()'s with_for_update fix (F3).

    Without a row lock, approve()'s db.get() -> status check -> mutate -> commit
    is a classic lost-update race: a second approve() call that reads the row
    before the first commits passes the PENDING guard, then blocks only at
    commit() on the row lock -- and once unblocked, Postgres's EvalPlanQual
    re-runs the UPDATE's WHERE id = :id clause (still true), so it silently
    overwrites the already-decided row instead of raising
    ApprovalAlreadyDecidedError. with_for_update=True moves the blocking point
    to the initial read, so the second call wakes up, re-reads the now-committed
    APPROVED status, and correctly raises.

    Same technique as
    test_clinical_document_service.test_ingest_document_blocks_concurrent_caller_until_first_releases_lock:
    a manually-held SELECT ... FOR UPDATE stands in for "another decision in
    flight" so the block is deterministic rather than relying on asyncio
    scheduling luck. Real cross-connection test: db_session's savepoint
    isolation can't prove this, since its writes never actually commit to the
    base transaction.
    """
    engine = create_async_engine(_PG_TEST_URL, echo=False)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as setup_session:
        admin = User(
            email=f"lock-admin-{uuid4().hex[:8]}@example.com",
            hashed_password="h",
            full_name="Lock Admin",
            role=UserRole.ADMIN,
        )
        setup_session.add(admin)
        await setup_session.commit()
        await setup_session.refresh(admin)

        request = await approval_service.create_approval_request(
            setup_session, action_type="email.reply.send", payload={"draft": "hello"}
        )
        request_id = request.id

    locking_session = async_session()
    second_session = async_session()
    try:
        locked_request = (
            await locking_session.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
            )
        ).scalar_one()

        second_call = asyncio.create_task(
            approval_service.approve(second_session, request_id, admin)
        )

        await asyncio.sleep(0.5)
        assert not second_call.done(), (
            "second approve() call should still be blocked on the row lock"
        )

        # Simulate the first decision winning while the lock is held.
        locked_request.status = ApprovalStatus.APPROVED
        locked_request.decided_at = utcnow()
        await locking_session.commit()

        with pytest.raises(ApprovalAlreadyDecidedError):
            await asyncio.wait_for(second_call, timeout=10)
    finally:
        await locking_session.close()
        await second_session.close()
        # audit_events is append-only (DB trigger blocks DELETE and, since
        # actor_id has ondelete="SET NULL", also blocks deleting the user that
        # generated one). Same cleanup convention as the clinical_document
        # lock test: the user and its audit rows are left in place.
        async with async_session() as cleanup_session:
            await cleanup_session.execute(
                delete(ApprovalRequest).where(ApprovalRequest.id == request_id)
            )
            await cleanup_session.commit()
        await engine.dispose()
