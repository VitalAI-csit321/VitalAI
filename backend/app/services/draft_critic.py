"""Deterministic draft critic (build spec §6).

Rules, not an LLM verdict: a restriction does not live in a prompt (§0 rule
5), and every extra model call is up to 90s behind a Semaphore(1). The
regeneration is the model call; the judgement is code. Add a rule only with a
named policy behind it.

Used by both paths: the agent graph (reject -> redraft, at most twice) and
the flag-off draft_reply (reject -> held for staff with the reason, no redraft).
"""

import re

# Prescription policy: staff may not tell a patient a medication is suitable
# for them; that is a clinician's call.
# ponytail: a phrase list, a naive heuristic. It catches the obvious wording
# and nothing paraphrased. Upgrade path is a trained classifier behind the
# same critique() signature, once a real policy corpus exists.
_SUITABILITY_PHRASES = (
    "appropriate to continue",
    "appropriate for you to take",
    "safe to continue",
    "safe for you to take",
    "fine to continue",
    "okay to continue",
    "ok to continue",
    "you can continue taking",
    "you should continue taking",
    "keep taking",
    "is suitable for you",
    "looks appropriate",
)

SUITABILITY_REASON = (
    "The draft judges whether a medication is suitable for the patient. Only a "
    "clinician can decide that; say the request has been passed to the clinical "
    "team instead."
)
# Onboarding policy (spec §9.0): email is not a secure channel, so a reply to
# someone we cannot yet identify must not invite health or financial details.
# ponytail: a term list, like the one above. It is deliberately broad, since a
# false reject only costs a redraft, while a false pass invites a patient to
# email their Medicare number.
_SENSITIVE_TERMS = (
    "medicare",
    "insurance",
    "health fund",
    "policy number",
    "concession",
    "credit card",
    "bank",
    "payment",
    "medical history",
    "medication",
    "allerg",
    "symptom",
    "diagnos",
)

SENSITIVE_REQUEST_REASON = (
    "The draft raises health or financial details with someone the clinic has not "
    "identified yet. Ask only for the missing contact details, and say the rest of "
    "registration is completed by phone or in the clinic."
)
EMPTY_REASON = "The draft is empty."

# Template artefacts (spec F.92, F.99): measured on 32 real drafts, 26 held a
# "[Patient Name]"-style placeholder and 19 held one inside a sentence.
# "Sincerely,\n[Your Name]\nClinic Administrator" is what the model writes when it
# has no name to sign with: a line that is only a placeholder is dropped at
# automatic send (drop_placeholder_lines) and filled by the human on the approval
# path. One inside a sentence would reach the patient as a hole, so that draft
# is rejected and goes to a person.
_PLACEHOLDER_LINE = re.compile(r"^\s*\[[^\]]{0,60}\]\s*$")
_INLINE_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,60}\]")

PLACEHOLDER_REASON = (
    "The draft still contains a placeholder such as [Patient Name]. Write the sentence "
    "without it; if a detail is unknown, leave it out rather than marking a gap."
)


def drop_placeholder_lines(draft: str) -> str:
    kept = [ln for ln in draft.splitlines() if not _PLACEHOLDER_LINE.match(ln)]
    return "\n".join(kept)


_UNVERIFIED_READER_BRANCHES = frozenset({"onboarding", "verification", "booking_conversation"})


def critique(draft: str | None, branch: str | None = None) -> str | None:
    """None if the draft passes, otherwise the reason it was rejected.

    branch adds the rules that apply to one agent only. It defaults to None,
    the shared rules, because critique() also runs on the live flag-off reply
    path: a global onboarding rule would hold every billing reply that
    mentions Medicare.
    """
    if draft is None or not draft.strip():
        return EMPTY_REASON
    text = draft.lower()
    if any(phrase in text for phrase in _SUITABILITY_PHRASES):
        return SUITABILITY_REASON
    if _INLINE_PLACEHOLDER.search(drop_placeholder_lines(draft)):
        return PLACEHOLDER_REASON
    # The conversation flow's templates go to the same kind of reader: someone
    # who may not be identified yet, over email.
    if branch in _UNVERIFIED_READER_BRANCHES and any(term in text for term in _SENSITIVE_TERMS):
        return SENSITIVE_REQUEST_REASON
    return None
