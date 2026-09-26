"""A computed second opinion on the LLM classifier's category (email only).

The LLM types its own confidence; measured offline it said 0.90 or 0.95 on every real email,
gibberish included (scripts/intent_classifier/RESULTS.md). This is a logistic regression over
the project's local nomic embeddings, so it does not depend on the LLM provider. When it
disagrees with the LLM, or is unsure itself (small top-1 minus top-2 margin), the caller
sends the email to a human.

The weights are plain numbers in app/ml/intent_regression.json, exported from
scripts/intent_classifier/evaluate_v2.py. No pickle and no scikit-learn at runtime.
Trained on email text only, so it must not be used on call transcripts.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from app.rag.embeddings import get_embedding_provider

_WEIGHTS = Path(__file__).resolve().parent.parent / "ml" / "intent_regression.json"


@lru_cache(maxsize=1)
def _weights() -> dict:
    return json.loads(_WEIGHTS.read_text())


def probabilities(vector: list[float]) -> dict[str, float]:
    """Softmax over the ten categories, the same as the regression's predict_proba."""
    w = _weights()
    scores = [
        sum(c * v for c, v in zip(row, vector, strict=True)) + b
        for row, b in zip(w["coef"], w["intercept"], strict=True)
    ]
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]
    total = sum(exps)
    return {label: e / total for label, e in zip(w["classes"], exps, strict=True)}


async def regression_view(text: str) -> tuple[str, float]:
    """The regression's category for this email and its top-1 minus top-2 margin."""
    # embed_documents, not embed_query: the weights were fitted on document embeddings.
    [vector] = await get_embedding_provider().embed_documents([text])
    ranked = sorted(probabilities(vector).items(), key=lambda kv: kv[1], reverse=True)
    return ranked[0][0], ranked[0][1] - ranked[1][1]
