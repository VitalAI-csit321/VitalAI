"""Response shape matches CSIT321_Capstone-frontend's api/types.ts::Message
field-for-field, so wiring the frontend later is a drop-in replacement of
listMessages()'s placeholder body, per that file's own comment.
"""

from pydantic import BaseModel


class InboxMessageOut(BaseModel):
    id: str
    caseId: str  # noqa: N815
    fromName: str  # noqa: N815
    fromInitials: str  # noqa: N815
    toName: str  # noqa: N815
    subject: str
    body: str
    priority: str  # "urgent" | "normal" | "fyi"
    category: str  # TaskCategory value, e.g. "prescription_renewal"
    unread: bool
    receivedLabel: str  # noqa: N815
    threadReference: str  # noqa: N815
    avatarColor: str  # noqa: N815
    draftText: str | None = None  # noqa: N815
    draftApprovalId: str | None = None  # noqa: N815
    draftSent: bool = False  # noqa: N815
    taskStatus: str = "pending"  # noqa: N815
    emailId: str | None = None  # noqa: N815
    handoverContext: str | None = None  # noqa: N815


class InboxListResponse(BaseModel):
    items: list[InboxMessageOut]
    total: int
