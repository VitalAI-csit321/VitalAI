"""The agent graph: thread identity, run context, nodes, and how a run is invoked."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import nodes
from app.agents.checkpointer import open_checkpointer
from app.agents.state import CaseState, Context
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.approval import ApprovalRequest
from app.models.task import TaskCategory
from app.models.user import User
from app.services import (
    approval_service,
    email_conversation_service,
    email_service,
    identity_service,
    task_service,
)
from app.services.reply_gate import ReplyWorthiness
from app.services.system_actor import get_or_create_agent_actor
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome

logger = logging.getLogger(__name__)

# State fields copied into the approval payload so the reviewer sees why the
# agent proposed what it did.
_REASONING_FIELDS = (
    "intent",
    "triage_category",
    "triage_confidence",
    "retrieval_sufficient",
    "retrieval_attempts",
    "reformulated_query",
    "critic_verdict",
    "critic_reason",
)


def thread_id(channel: str, source_id: str) -> str:
    """One thread per inbound message, never per case.

    source_id is the channel's own row id (Email.id for email). An
    IntakeCase holds many messages (ingest_email reuses an existing case,
    Email.case_id is a non-unique FK). Keying threads on case_id would let a
    second email inherit the first one's draft and approval and collide with
    its pending resume.
    """
    return f"{channel}:{source_id}"


def run_config(tid: str) -> RunnableConfig:
    return {"configurable": {"thread_id": tid}}


async def make_context(session_factory: async_sessionmaker[AsyncSession]) -> Context:
    async with session_factory() as db:
        actor = await get_or_create_agent_actor(db)
    return Context(session_factory=session_factory, actor_id=actor.id)


async def create_approval(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Write the ApprovalRequest (and its audit event). Runs exactly once.

    Kept apart from await_approval on purpose: interrupt() re-runs its whole
    node on resume, so a row written next to it would be written again on
    every resume. As its own node this one finishes its super-step and is
    checkpointed as done before the interrupt happens.
    """
    tid = thread_id(state["channel"], state["source_id"])
    async with runtime.context.session_factory() as db:
        actor = await db.get(User, runtime.context.actor_id)
        request = await approval_service.create_approval_request(
            db,
            # The existing approved-reply executor handles this action type,
            # including P1's draft_sent guard, so approval dispatches exactly
            # what the human approved.
            action_type="email.draft_reply",
            payload={
                "draft": state.get("draft_text"),
                "email_id": state["source_id"] if state["channel"] == "email" else None,
                "task_id": state.get("task_id"),
                "risk_tier": state.get("risk_tier"),
                "reasoning": {
                    k: v for k, v in state.items() if k in _REASONING_FIELDS and v is not None
                },
                # An auto-send that failed to deliver lands here; the reviewer
                # needs to know why it did not simply go out.
                **(
                    {"delivery_error": state["delivery_error"]}
                    if state.get("delivery_error")
                    else {}
                ),
            },
            case_id=UUID(state["case_id"]) if state.get("case_id") else None,
            requested_by=actor,
            external_ref=tid,
        )
        # Same Task columns draft_reply sets, so the inbox shows the draft and
        # its pending approval whichever path produced them.
        if state.get("task_id"):
            await email_service.persist_draft(
                db, state["task_id"], state.get("draft_text"), approval_id=str(request.id)
            )
    return {"approval_request_id": str(request.id), "approval_status": request.status.value}


async def await_approval(state: CaseState) -> dict:
    """Pause until a human decides. Calls interrupt() and nothing else.

    This node re-runs from the top on resume, so it must stay free of side
    effects. It is the graph's ONLY interrupt node: a second one would leave
    threads with several pending interrupts, and LangGraph then refuses a
    plain Command(resume=...) ("When there are multiple pending interrupts,
    you must specify the interrupt id when resuming"). Adding one means
    switching every resume to interrupt-id-keyed resume values.
    """
    decision = interrupt({"approval_request_id": state["approval_request_id"]})
    update: dict = {
        "approval_status": "approved" if decision.get("approved") else "rejected",
        # The executor's own outcome, not an earlier auto-send failure's.
        "delivery_error": decision.get("error") if decision.get("delivered") is False else None,
    }
    if decision.get("draft") is not None:
        update["draft_text"] = decision["draft"]
    return update


# --- routing (§4.3) -----------------------------------------------------------

# No agent, ever: an emergency or a complaint must never receive a generated
# draft. "Human review" is the Task ingest_email already created, so the graph
# just ends. The routing gate forces HUMAN_REVIEW for both categories too
# (task_routing_gate.py); this is the second, independent check.
_HUMAN_ONLY = frozenset({TaskCategory.URGENT_EMERGENCY, TaskCategory.COMPLAINT_ESCALATION})

# PLACEHOLDER EDGES. These agents arrive in §9-§12. Until each one lands its
# intent takes the existing draft path, exactly as the flag-off pipeline does,
# so the two stay in parity. Replace the entry in _PATHS when its agent exists.
_AGENT_FOR_INTENT = {
    TaskCategory.APPOINTMENT_REQUEST: "booking",
    TaskCategory.MEDICAL_RECORDS_REQUEST: "records",
    TaskCategory.PRESCRIPTION_RENEWAL: "prescription",
    TaskCategory.NEW_PATIENT_ONBOARDING: "onboarding",
}

# §9: a provisional (not yet verified) patient must not reach these at all.
# Checked here, before any agent runs, not left to each agent to remember.
# Nothing creates provisional patients until onboarding (§9) lands, so this
# cannot diverge from the flag-off path yet.
_NOT_FOR_PROVISIONAL = frozenset({"booking", "records", "prescription"})

# The agents that have a node of their own (§10, §11). They are reached only
# from route_identity, after the sender is known: identity runs after the reply
# gate, so route_intent's entries for them are still placeholders into it.
# Every other name in _AGENT_FOR_INTENT keeps the ordinary draft path.
_BRANCH_NODES = frozenset({"booking", "records", "prescription"})


def route_intent(state: CaseState) -> str:
    """Which agent handles this message. Pure function of state."""
    intent = TaskCategory(i) if (i := state.get("intent")) else None
    review = state.get("routing_outcome") == TaskRoutingOutcome.HUMAN_REVIEW
    if intent in _HUMAN_ONLY or (review and state.get("routing_override")):
        return "human_review"
    # A reply in an open email conversation (set by load only with the flag
    # on) skips the reply gate, which would judge "Tuesday 10am works" not
    # worth answering, and identity, which the conversation already settled.
    # Low classifier confidence alone does not end it either: "The second one
    # please" is nothing like a first email, and the conversation node checks
    # its own extraction confidence. Red flags and complaints still win above.
    if state.get("conversation_id"):
        return "conversation"
    if review:
        return "human_review"
    agent = _AGENT_FOR_INTENT.get(intent, "retrieval") if intent else "retrieval"
    if state.get("is_provisional") and agent in _NOT_FOR_PROVISIONAL:
        return "human_review"
    return agent


def route_after_consent(state: CaseState) -> str:
    """Voicemail never drafts (spec D6): urgent ones already have their
    script; the rest go to caller matching. Email is route_intent, unchanged."""
    if state.get("channel") == "voicemail":
        return END if state.get("urgent") else "voicemail_identity"
    return route_intent(state)


def after_voicemail_identity(state: CaseState) -> str:
    if (
        state.get("intent") == TaskCategory.APPOINTMENT_REQUEST.value
        and state.get("patient_id")
        and not state.get("is_provisional")
    ):
        return "booking"
    if (
        state.get("identity_outcome") == identity_service.IdentityOutcome.NO_MATCH.value
        and state.get("intent") in identity_service.ONBOARDING_INTENTS
    ):
        return "voicemail_onboarding"
    return "callback"


def after_booking(state: CaseState) -> str:
    if state.get("channel") == "voicemail":
        return "callback"  # a hold still gets a script, saying "book by hand"
    return END if state.get("dispatch_result") == "booking_hold" else "draft"


def route_identity(state: CaseState) -> str:
    """§8.2, after the reply gate: intent x identity outcome x provisional.

    Only patient-specific intents are blocked; a general question drafts
    whatever the outcome. The provisional check is re-applied because
    identity can link a provisional patient that load did not know about.
    """
    intent = TaskCategory(i) if (i := state.get("intent")) else None
    if intent not in identity_service.PATIENT_SPECIFIC:
        return "draft"
    outcome = identity_service.IdentityOutcome(state["identity_outcome"])
    # The email conversation flow: an appointment request becomes a
    # conversation (provisional patients included, which is the point), and a
    # sender nobody can identify is asked to verify rather than left waiting.
    conversations = email_conversation_service.enabled()
    booking = conversations and intent == TaskCategory.APPOINTMENT_REQUEST
    if outcome == identity_service.IdentityOutcome.MATCHED:
        if booking:
            return "conversation"
        agent = _AGENT_FOR_INTENT.get(intent, "retrieval")
        if state.get("is_provisional") and agent in _NOT_FOR_PROVISIONAL:
            return "staff"
        return agent if agent in _BRANCH_NODES else "draft"
    if (
        outcome == identity_service.IdentityOutcome.NO_MATCH
        and intent in identity_service.ONBOARDING_INTENTS
    ):
        if booking:
            return "conversation"
        # No name, no provisional record: ask for the details rather than
        # leave "how do I sign up?" with no reply at all.
        if conversations and not (state.get("identity_fields") or {}).get("name"):
            return "request_verification"
        return "onboarding"
    return "request_verification" if conversations else "staff"


def after_conversation(state: CaseState) -> str:
    if state.get("dispatch_result") == "conversation_hold":
        return END
    if state.get("conversation_resume"):
        return route_identity(state)
    if state.get("booking_choice"):
        return "book"
    return "draft"


def auto_send_or_approve(state: CaseState) -> str:
    """The same predicate draft_reply uses, plus the rule that a HIGH risk
    tier (email_service.reply_risk_tier) always reaches a human.

    For a draft the critic passed first time the two paths make the same
    decision. They are not the same for every email: a draft the critic
    rejected is held for staff on the flag-off path, and redrafted here; the
    redraft is HIGH, so it reaches a human too and neither path auto-sends it."""
    if state.get("risk_tier") == "high":
        return "create_approval"
    # The conversation flow's fixed texts (email_service.TEMPLATE_BRANCHES):
    # they go out on their own, unless auto-send is switched off entirely.
    if state.get("risk_tier") == "template":
        return "auto_send" if settings.email_auto_send_enabled else "create_approval"
    eligible = email_service.auto_send_eligible(
        verdict=ReplyWorthiness(state["reply_verdict"]),
        gate_outcome=TaskRoutingOutcome(state["routing_outcome"]),
        confidence=state["triage_confidence"],
        grounded=bool(state.get("grounded")),
        category=TaskCategory(i) if (i := state.get("intent")) else None,
    )
    return "auto_send" if eligible else "create_approval"


# At most two regenerations, so three drafts in all (Appendix F.5). Enforced
# here, by the edge, not by the model deciding it has done enough.
MAX_REGENERATIONS = 2


def after_critic(state: CaseState) -> str:
    if state["critic_verdict"] == "pass":
        return "guardrail"
    if state.get("revision_count", 0) < MAX_REGENERATIONS:
        return "draft"
    return "escalate"


# --- failure path (§4.1) ------------------------------------------------------

Node = Callable[..., Awaitable[dict]]


def _guarded(stage: str, fn: Node) -> Node:
    """A node that raises must not make the case vanish.

    A graph run launched in the background swallows exceptions, so without
    this an LLM outage mid-graph would leave nothing but a log line. Instead:
    audit event plus a visible Task (task_service.record_agent_failure), then
    the error field sends every edge to END.
    """

    async def node(state: CaseState, runtime: Runtime[Context]) -> dict:
        try:
            return await fn(state, runtime)
        except GraphBubbleUp:
            raise  # interrupt() and friends are control flow, not failures
        except Exception as exc:
            logger.exception("Agent node %s failed for %s", stage, state.get("source_id"))
            try:
                async with runtime.context.session_factory() as db:
                    actor = await get_or_create_agent_actor(db)
                    await task_service.record_agent_failure(
                        db,
                        task_id=state.get("task_id"),
                        case_id=state.get("case_id"),
                        actor=actor,
                        stage=stage,
                        error_type=type(exc).__name__,
                        error_detail=str(exc),
                    )
            except Exception:
                logger.exception("Could not record the %s failure", stage)
            return {"error": f"{stage}: {type(exc).__name__}"}

    node.__name__ = stage
    return node


def _unless_failed(route: Callable[[CaseState], str]) -> Callable[[CaseState], str]:
    def edge(state: CaseState) -> str:
        return END if state.get("error") else route(state)

    return edge


def _to(target: str) -> Callable[[CaseState], str]:
    return _unless_failed(lambda _: target)


def build_graph() -> StateGraph[CaseState, Context, CaseState, CaseState]:
    builder = StateGraph(CaseState, context_schema=Context)
    for name, fn in (
        ("load", nodes.load),
        ("consent", nodes.consent),
        ("reply_gate", nodes.reply_gate),
        ("identity", nodes.identity),
        ("onboarding", nodes.onboarding),
        ("booking", nodes.booking),
        ("records", nodes.records),
        ("prescription", nodes.prescription),
        ("identity_hold", nodes.identity_hold),
        ("conversation", nodes.conversation),
        ("book", nodes.book),
        ("request_verification", nodes.request_verification),
        ("draft", nodes.draft),
        ("escalate", nodes.escalate),
        ("guardrail", nodes.guardrail),
        ("auto_send", nodes.auto_send),
        ("create_approval", create_approval),
        ("dispatch", nodes.dispatch),
        ("voicemail_identity", nodes.voicemail_identity),
        ("voicemail_onboarding", nodes.voicemail_onboarding),
        ("callback", nodes.callback),
    ):
        builder.add_node(name, _guarded(name, fn))
    builder.add_node("risk", nodes.risk)
    builder.add_node("critic", nodes.critic)
    # Not guarded: interrupt() raises to pause, and this node has no side
    # effects to fail.
    builder.add_node("await_approval", await_approval)

    builder.add_edge(START, "load")
    builder.add_conditional_edges("load", _to("consent"))
    builder.add_conditional_edges(
        "consent",
        _unless_failed(route_after_consent),
        {
            "human_review": END,
            "retrieval": "reply_gate",
            # Placeholder edges, see _AGENT_FOR_INTENT.
            "booking": "reply_gate",
            "records": "reply_gate",
            "prescription": "reply_gate",
            "onboarding": "reply_gate",
            "conversation": "conversation",
            "voicemail_identity": "voicemail_identity",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "reply_gate",
        _unless_failed(lambda s: END if s.get("dispatch_result") == "not_worthy" else "identity"),
    )
    builder.add_conditional_edges(
        "identity",
        _unless_failed(route_identity),
        {
            "draft": "draft",
            "staff": "identity_hold",
            "onboarding": "onboarding",
            "booking": "booking",
            "records": "records",
            "prescription": "prescription",
            "conversation": "conversation",
            "request_verification": "request_verification",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "conversation",
        _unless_failed(after_conversation),
        {
            "draft": "draft",
            "book": "book",
            # A verified sender's original inquiry, routed by route_identity.
            "staff": "identity_hold",
            "records": "records",
            "prescription": "prescription",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "book",
        _unless_failed(
            lambda s: END if s.get("dispatch_result") == "conversation_hold" else "draft"
        ),
    )
    builder.add_conditional_edges(
        "request_verification",
        _unless_failed(lambda s: END if s.get("dispatch_result") == "identity_hold" else "draft"),
    )
    builder.add_conditional_edges(
        "onboarding",
        _unless_failed(lambda s: END if s.get("dispatch_result") == "identity_hold" else "draft"),
    )
    # No doctor or no free time: the reason is on the Task and nothing is drafted.
    builder.add_conditional_edges("booking", _unless_failed(after_booking))
    builder.add_conditional_edges("voicemail_identity", _unless_failed(after_voicemail_identity))
    builder.add_conditional_edges("voicemail_onboarding", _to("callback"))
    builder.add_edge("callback", END)
    builder.add_conditional_edges("records", _to("draft"))
    builder.add_conditional_edges("prescription", _to("draft"))
    builder.add_edge("identity_hold", END)
    # Critic first (policy), then the output guardrail (safety). Both run.
    builder.add_conditional_edges("draft", _to("critic"))
    builder.add_conditional_edges("critic", after_critic)
    builder.add_edge("escalate", END)
    builder.add_conditional_edges(
        "guardrail",
        _unless_failed(lambda s: END if s.get("dispatch_result") == "blocked" else "risk"),
    )
    builder.add_conditional_edges("risk", auto_send_or_approve)
    builder.add_conditional_edges(
        "auto_send",
        _unless_failed(lambda s: "create_approval" if s.get("delivery_error") else END),
    )
    builder.add_conditional_edges("create_approval", _to("await_approval"))
    # A rejection must reach END too, or the thread stays paused forever.
    builder.add_conditional_edges(
        "await_approval", lambda s: "dispatch" if s["approval_status"] == "approved" else END
    )
    builder.add_edge("dispatch", END)
    return builder


async def run(tid: str, graph_input: CaseState | Command) -> dict[str, Any]:
    """Start or resume one thread against the Postgres checkpointer.

    durability="sync": each super-step's checkpoint is written before the
    next one starts, so create_approval is recorded as done before
    await_approval runs.
    """
    async with open_checkpointer() as saver:
        graph = build_graph().compile(checkpointer=saver)
        return await graph.ainvoke(
            graph_input,
            run_config(tid),
            context=await make_context(AsyncSessionLocal),
            durability="sync",
        )


async def start(
    task_id: UUID,
    email_id: UUID,
    actor_id: UUID,
    gate: TaskRoutingGateResult,
    confidence: float,
) -> None:
    """Run the reply graph for one ingested email.

    Same signature as email_service.draft_reply_detached, which it replaces
    when agentic_pipeline_enabled is on, so both schedulers swap one callable
    for the other. actor_id is the ingesting user; the graph acts as the
    agent actor instead (Context), so it is unused here.
    """
    tid = thread_id("email", str(email_id))
    try:
        await run(
            tid,
            {
                "channel": "email",
                # Email.id, never external_id: that is null for direct ingest.
                "source_id": str(email_id),
                "task_id": str(task_id),
                "routing_outcome": gate.outcome.value,
                "routing_override": gate.override_reason,
                "triage_confidence": confidence,
                "revision_count": 0,
            },
        )
    except Exception as exc:
        # Node failures are handled inside the graph (_guarded). This catches
        # what is left, the checkpointer or the run itself failing, which has
        # nobody to raise to from a background task.
        logger.exception("Agent graph run failed for thread %s", tid)
        await _record_run_failure("run", exc, task_id=task_id)


async def start_voicemail(task_id: UUID, call_id: UUID, *, urgent: bool) -> None:
    """Run the graph for one processed voicemail (voicemail spec §8)."""
    tid = thread_id("voicemail", str(call_id))
    try:
        await run(
            tid,
            {
                "channel": "voicemail",
                "source_id": str(call_id),
                "task_id": str(task_id),
                "urgent": urgent,
                "revision_count": 0,
            },
        )
    except Exception as exc:
        logger.exception("Agent graph run failed for thread %s", tid)
        await _record_run_failure("run", exc, task_id=task_id)


async def resume(tid: str, decision: dict) -> None:
    """Scheduled entry point for an approve/reject decision."""
    try:
        await run(tid, Command(resume=decision))
    except Exception as exc:
        # A background task's exception goes nowhere. The approval row is
        # already decided and is what the queue shows; the Task says the
        # thread did not finish.
        logger.exception("Agent graph resume failed for thread %s", tid)
        await _record_run_failure("resume", exc, tid=tid)


async def _record_run_failure(
    stage: str, exc: Exception, *, task_id: UUID | None = None, tid: str | None = None
) -> None:
    """The failure path for what _guarded cannot see: the checkpointer or the
    run failing outside any node. Same outcome, audit event plus a visible
    Task. A resume knows only its thread, so its Task comes off the approval
    row that thread created."""
    try:
        async with AsyncSessionLocal() as db:
            if task_id is None and tid is not None:
                row = (
                    await db.execute(
                        select(ApprovalRequest)
                        .where(ApprovalRequest.external_ref == tid)
                        .order_by(ApprovalRequest.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row is not None and row.payload.get("task_id"):
                    task_id = UUID(row.payload["task_id"])
            actor = await get_or_create_agent_actor(db)
            await task_service.record_agent_failure(
                db,
                task_id=task_id,
                case_id=None,
                actor=actor,
                stage=stage,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
    except Exception:
        logger.exception("Could not record the %s failure for %s", stage, tid or task_id)
