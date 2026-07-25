from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalStatus
from app.models.audit import AuditEvent
from app.models.user import User, UserRole
from app.services import approval_service
from app.services.approval_service import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalNotGrantedError,
)


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
    assert len(events) == 1
    assert events[0].details["approval_id"] == str(request.id)


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
    assert len(events) == 1


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
    admin = _user(UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()
    a = await approval_service.create_approval_request(
        db_session, action_type="email.reply.send", payload={}
    )
    b = await approval_service.create_approval_request(
        db_session, action_type="call.escalation.route", payload={}
    )
    await approval_service.approve(db_session, a.id, admin)

    pending_items, pending_total = await approval_service.list_approvals(
        db_session, status=ApprovalStatus.PENDING
    )
    assert pending_total == 1
    assert pending_items[0].id == b.id

    email_items, email_total = await approval_service.list_approvals(
        db_session, action_type="email.reply.send"
    )
    assert email_total == 1
    assert email_items[0].id == a.id


async def test_list_approvals_paginates(db_session: AsyncSession):
    for i in range(3):
        await approval_service.create_approval_request(
            db_session, action_type=f"email.reply.send.{i}", payload={}
        )

    items, total = await approval_service.list_approvals(db_session, limit=2, offset=0)
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
