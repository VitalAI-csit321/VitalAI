"""Response shape matches CSIT321_Capstone-frontend's api/types.ts::Message
field-for-field, so wiring the frontend later is a drop-in replacement of
listMessages()'s placeholder body, per that file's own comment.
"""

from typing import Annotated

from pydantic import BaseModel, StringConstraints


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
    callId: str | None = None  # noqa: N815
    hasAudio: bool = False  # noqa: N815
    # Server-decided (review queue spec section 7): the UI never infers approve rights.
    canApprove: bool = False  # noqa: N815
    reviewItemId: str | None = None  # noqa: N815
    # Write reply (D14): an email nothing was sent on and no draft awaits approval.
    canWriteReply: bool = False  # noqa: N815
    # The case chip (M4): the confirmed patient, and the case the message is in.
    patientId: str | None = None  # noqa: N815
    episodeId: str | None = None  # noqa: N815
    episodeTitle: str | None = None  # noqa: N815


class InboxListResponse(BaseModel):
    items: list[InboxMessageOut]
    total: int


class WriteReplyBody(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
