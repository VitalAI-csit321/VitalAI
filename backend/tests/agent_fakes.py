"""Fakes shared by the agent graph tests and their cross-process worker.

Plain module, no pytest: tests/agent_xproc_worker.py runs in a second
interpreter and needs the same seeding and the same fake model.
"""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase, IntakeStatus
from app.models.email import Email
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.services.task_routing_rules import resolve_target_role

DRAFT = "Thanks, we have your request."


class FakeLLM:
    """Answers each of the pipeline's three prompt kinds: the reply-worthiness
    gate, a draft (plain reply or RAG answer), and the classifier. Records
    every prompt so a test can see what the model was asked."""

    def __init__(
        self,
        category: str = "general_administrative",
        confidence: float = 0.95,
        replies: list[str] | None = None,
        worthy: bool = True,
    ):
        self.category = category
        self.confidence = confidence
        self.replies = list(replies or [DRAFT])
        self.worthy = worthy
        self.prompts: list[str] = []

    @property
    def draft_prompts(self) -> list[str]:
        return [p for p in self.prompts if _is_draft(p)]

    async def ainvoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": self.worthy, "reason": "test verdict"})
        if _is_draft(prompt):
            # One reply per draft, the last one repeating.
            return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps({"category": self.category, "confidence": self.confidence})


def _is_draft(prompt: str) -> bool:
    return prompt.rstrip().endswith(("REPLY:", "ANSWER:"))


async def seed_email(
    db: AsyncSession,
    *,
    email_id: UUID | None = None,
    category: TaskCategory = TaskCategory.GENERAL_ADMINISTRATIVE,
    body: str = "What time do you open on Saturdays?",
    external_id: str | None = None,
    case_id: UUID | None = None,
) -> tuple[Email, Task]:
    """The rows ingest_email commits, without its classifier call."""
    if case_id is None:
        case = IntakeCase(
            contact_reason="Question", contact_channel="email", status=IntakeStatus.RECEIVED
        )
        db.add(case)
        await db.flush()
        case_id = case.id
    email = Email(
        id=email_id or uuid4(),
        case_id=case_id,
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Question",
        body=body,
        received_at=datetime.now(UTC),
        external_id=external_id,
        external_source="outlook" if external_id else None,
    )
    task = Task(
        case_id=case_id,
        source=TaskSource.EMAIL,
        category=category,
        target_role=resolve_target_role(category),
        priority=TaskPriority.MEDIUM,
        status=TaskItemStatus.PENDING,
    )
    db.add_all([email, task])
    await db.commit()
    return email, task


def graph_input(email, task, outcome: str = "auto_routed_flagged", confidence=0.8) -> dict:
    """What graph.start passes in. A flagged (not fully confident) outcome
    fails the auto-send predicate, so the run pauses for approval."""
    return {
        "channel": "email",
        "source_id": str(email.id),
        "task_id": str(task.id),
        "routing_outcome": outcome,
        "triage_confidence": confidence,
        "revision_count": 0,
    }
