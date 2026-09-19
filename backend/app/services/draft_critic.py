"""Deterministic draft critic (build spec §6).

Rules, not an LLM verdict: a restriction does not live in a prompt (§0 rule
5), and every extra model call is up to 90s behind a Semaphore(1). The
regeneration is the model call; the judgement is code. Add a rule only with a
named policy behind it.

Used by both paths: the agent graph (reject -> redraft, at most twice) and
the flag-off draft_reply (reject -> held for staff with the reason, no redraft).
"""

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
EMPTY_REASON = "The draft is empty."


def critique(draft: str | None) -> str | None:
    """None if the draft passes, otherwise the reason it was rejected."""
    if draft is None or not draft.strip():
        return EMPTY_REASON
    text = draft.lower()
    if any(phrase in text for phrase in _SUITABILITY_PHRASES):
        return SUITABILITY_REASON
    return None
