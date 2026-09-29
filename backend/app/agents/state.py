"""Graph state and run context.

CaseState is what LangGraph checkpoints: flat, JSON-friendly, and updated
only by nodes returning partial dicts. IDs are strings so the checkpoint
serialiser never has to know about UUIDs.

Context is what the graph must NOT checkpoint. An AsyncSession is not
serialisable, and holding one across an interrupt() that waits days for a
human would pin a pooled connection the whole time. So the context carries
a session factory, each node opens and commits its own session, and the
context is supplied fresh on every invoke/resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class CaseState(TypedDict, total=False):
    # A key is absent until a node sets it. `| None` marks the keys some
    # node really writes None to; the rest only ever hold a value.
    case_id: str | None
    # Not in the spec's field list, but §3's approval payload needs it and
    # the approved-reply executor reads draft_sent off this Task.
    task_id: str
    channel: str
    source_id: str
    sender_identifier: str | None
    # Voicemail only: process() already wrote the urgent script, so the graph
    # stops after consent.
    urgent: bool | None
    content: str | None

    patient_id: str | None
    patient_name: str | None
    patient_status: str | None
    is_provisional: bool | None
    identity_outcome: str
    # Voicemail only: "created" or "existing" provisional record for an
    # unknown caller, None when nobody was onboarded.
    voicemail_onboarding: str | None
    # What the sender said about themselves (§8.3), for onboarding. JSON-safe:
    # dob as an ISO string.
    identity_fields: dict | None

    consent_status: str | None

    intent: str | None
    triage_category: str | None
    triage_confidence: float
    # The task routing gate's outcome, computed once by ingest_email. Carried
    # in, not recomputed, the same way draft_reply_detached receives it.
    routing_outcome: str
    # The gate's safety override (urgent_keyword, complaint_category,
    # urgent_category); None when HUMAN_REVIEW was only low confidence.
    routing_override: str | None
    reply_verdict: str

    retrieval_results: list[dict]
    retrieval_sufficient: bool | None
    retrieval_attempts: int
    reformulated_query: str | None

    # Which agent is drafting: None for the ordinary reply path, "onboarding"
    # for a provisional patient's first reply. The critic reads it too.
    branch: str | None
    requested_fields: list[str]
    # §10: ISO instants, UTC-aware, rendered in clinic local time by the
    # template. The doctor is the one the patient is actually assigned to.
    proposed_slots: list[str]
    booking_doctor_name: str
    # §11: explicit captured consent, which an implied inbound-contact record
    # is not.
    records_consent: bool | None
    # §12: which of the two prescription acknowledgements applies. Decided by
    # the medication history, which the draft itself never sees.
    prescription_review_due: bool | None

    # The email conversation flow (email_conversation_service). The row that
    # carries one turn's facts to the next; the fixed text this turn replies
    # with; the stage and offered times to record once it has really been
    # sent; the offered time a patient just picked; and, after a verification
    # reply identified the sender, the email whose inquiry should be answered.
    conversation_id: str
    template_text: str | None
    next_stage: str | None
    offer: list[dict]
    # True when the template being sent is the registration form link, so
    # record_sent stamps form_sent_at once it has really gone out.
    form_link: bool | None
    booking_choice: dict
    conversation_resume: bool | None
    content_email_id: str | None

    draft_text: str | None
    grounded: bool | None
    critic_verdict: str | None
    critic_reason: str | None
    revision_count: int

    risk_tier: str | None

    approval_request_id: str | None
    approval_status: str | None

    # How the thread ended: sent, send_failed, blocked, not_worthy, escalated.
    dispatch_result: str | None
    # Why the last delivery attempt failed, auto-send or approved send.
    delivery_error: str | None
    # Set by the failure path when a node raised; every edge then goes to END.
    error: str | None

    audit_refs: list[str]


@dataclass(frozen=True)
class Context:
    session_factory: async_sessionmaker[AsyncSession]
    # The seeded agent User (app/services/system_actor.py). An ID, not the
    # row: a User loaded in one node's session is detached in the next.
    actor_id: UUID
