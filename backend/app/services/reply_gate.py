"""Reply-worthiness gate: does an incoming email deserve a reply at all?

Exists so auto-send can be re-enabled safely (see email_service.draft_reply).
Deterministic sender pre-filter first (no LLM, catches the Microsoft/bank
notification mail actually seen in live testing at zero cost), then LLM
reasoning through guarded_invoke for anything that survives it -- email
bodies are untrusted input, same reasoning as content_classifier.

Three states, not a boolean, mirroring evaluate_task_routing_gate's shape:
WORTHY / NOT_WORTHY / UNCERTAIN. UNCERTAIN is the fail-safe for a parse
failure or a guardrail block -- it never auto-sends and never silently drops,
it always still gets a draft + human approval.

Deliberately skipped: RFC 3834 Auto-Submitted / List-Unsubscribe / Precedence
header checks. Standards-correct but need internetMessageHeaders threaded
through Graph $select -> EmailIngestRequest -> here. Sender patterns plus the
LLM cover the observed cases.
# ponytail: sender-substring + LLM only, add header checks if spam volume grows
"""

from __future__ import annotations

import enum
import json
import logging

from langchain_core.language_models import BaseLanguageModel
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.guardrail import InputBlockedError, guarded_invoke
from app.models.user import User

logger = logging.getLogger(__name__)

AUTOMATED_LOCAL_PARTS: tuple[str, ...] = (
    "noreply",
    "no-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "bounce",
)

_PROMPT_TEMPLATE = """You are triaging incoming email for a GP clinic's admin inbox.
Decide whether this email deserves a reply from the clinic (a patient question,
request, or complaint) versus not (a promotional/marketing email, an automated
notification, spam, or anything with no request to respond to).

Respond with ONLY a JSON object, no other text, in this exact shape:
{{"worthy": <true or false>, "reason": "<one short sentence>"}}

SUBJECT: {subject}
BODY: {body}

JSON:"""


class ReplyWorthiness(enum.StrEnum):
    WORTHY = "worthy"
    NOT_WORTHY = "not_worthy"
    UNCERTAIN = "uncertain"


class ReplyGateResult(BaseModel):
    verdict: ReplyWorthiness
    reason: str


class _ParseError(Exception):
    pass


def _sender_local_part(sender: str) -> str:
    return sender.split("@", 1)[0].lower()


def _is_automated_sender(sender: str) -> bool:
    local_part = _sender_local_part(sender)
    return any(pattern in local_part for pattern in AUTOMATED_LOCAL_PARTS)


def _parse_verdict(raw: str) -> ReplyGateResult:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise _ParseError(f"No JSON object found: {raw!r}")
    try:
        parsed = json.loads(text[start : end + 1])
        worthy = bool(parsed["worthy"])
        reason = str(parsed["reason"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise _ParseError(f"Malformed payload: {raw!r}") from exc
    return ReplyGateResult(
        verdict=ReplyWorthiness.WORTHY if worthy else ReplyWorthiness.NOT_WORTHY, reason=reason
    )


async def evaluate_reply_worthiness(
    db: AsyncSession,
    llm: BaseLanguageModel,
    *,
    sender: str,
    subject: str,
    body: str,
    actor: User,
) -> ReplyGateResult:
    if _is_automated_sender(sender):
        return ReplyGateResult(
            verdict=ReplyWorthiness.NOT_WORTHY, reason=f"automated sender ({sender})"
        )

    prompt = _PROMPT_TEMPLATE.format(subject=subject, body=body)
    try:
        raw = await guarded_invoke(db, llm, prompt, actor=actor, route="email.reply_gate")
    except InputBlockedError:
        logger.warning("evaluate_reply_worthiness: guardrail blocked email content")
        return ReplyGateResult(verdict=ReplyWorthiness.UNCERTAIN, reason="guardrail blocked")

    raw_text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
    try:
        return _parse_verdict(raw_text)
    except _ParseError:
        logger.exception("evaluate_reply_worthiness: failed to parse gate output")
        return ReplyGateResult(verdict=ReplyWorthiness.UNCERTAIN, reason="unparseable gate output")
