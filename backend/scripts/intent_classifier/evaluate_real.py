"""Measure the saved regression and the LLM classifier on the real vitalai_qa emails.

Labels come from real_labels.jsonl, committed before this script first ran. The email text
is read from vitalai_qa in a read-only session and never written to disk, because it holds
real addresses. No retraining: model.joblib is used as saved.

    cd backend
    ../../CSIT321_Capstone/backend/.venv/bin/python -m scripts.intent_classifier.evaluate_real
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncpg
import joblib
import numpy as np
from sklearn.metrics import roc_auc_score
from sqlalchemy.engine import make_url

from app.config import settings
from app.models.task import TaskCategory
from app.rag.embeddings import get_embedding_provider
from app.services.task_routing_gate import evaluate_task_routing_gate
from app.services.triage_service import is_urgent
from scripts.intent_classifier.evaluate import evaluate, run_llm, spread

HERE = Path(__file__).parent
TARGET_ACCURACY = 0.95  # fixed in commit 7a8c740, before any prediction was made
SPLIT_SEED = 0


async def fetch_emails() -> dict[str, dict]:
    url = make_url(settings.database_url).set(drivername="postgresql", database="vitalai_qa")
    conn = await asyncpg.connect(
        url.render_as_string(hide_password=False),
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        rows = await conn.fetch("select id::text as id, subject, body from emails")
    finally:
        await conn.close()
    return {r["id"]: dict(r) for r in rows}


def regression(texts: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    # Pickle-based, safe only because evaluate.py in this directory wrote it. Never load one
    # from elsewhere.
    saved = joblib.load(HERE / "model.joblib")
    emb = np.array(asyncio.run(get_embedding_provider().embed_documents(texts)))
    proba = saved["model"].predict_proba(emb)
    order = np.argsort(proba, axis=1)
    rows = np.arange(len(texts))
    top1 = proba[rows, order[:, -1]]
    return list(saved["model"].classes_[order[:, -1]]), top1, top1 - proba[rows, order[:, -2]]


def auroc(correct: list[bool], score: np.ndarray) -> float | None:
    return float(roc_auc_score(correct, score)) if 0 < sum(correct) < len(correct) else None


def pick_threshold(margin: np.ndarray, correct: np.ndarray) -> float | None:
    """Smallest margin whose auto-routed set (margin >= t) is at least TARGET_ACCURACY right."""
    for t in sorted(set(margin.tolist())):
        if correct[margin >= t].mean() >= TARGET_ACCURACY:
            return t
    return None


def main() -> None:
    labels = [json.loads(ln) for ln in (HERE / "real_labels.jsonl").read_text().splitlines()]
    emails = asyncio.run(fetch_emails())
    assert {lab["email_id"] for lab in labels} == set(emails), "labels and vitalai_qa disagree"
    # The exact text production classifies (email_service.py builds it the same way).
    texts = [
        f"Subject: {emails[lab['email_id']]['subject']}\n\n{emails[lab['email_id']]['body']}"
        for lab in labels
    ]
    bodies = [emails[lab["email_id"]]["body"] for lab in labels]
    y = [lab["label"] for lab in labels]

    lr_pred, lr_top1, lr_margin = regression(texts)
    lr_body_pred, _, _ = regression(bodies)  # diagnostic only: the regression trained on bodies
    llm_out = asyncio.run(run_llm(texts))
    llm_pred = [o["category"] for o in llm_out]
    llm_conf = np.array([o["confidence"] for o in llm_out])

    in_scope = [i for i, lab in enumerate(y) if lab != "out_of_scope"]
    dedup, seen = [], set()
    for i in in_scope:
        key = bodies[i].strip().lower()
        if key not in seen:
            seen.add(key)
            dedup.append(i)
    clear = [i for i in in_scope if labels[i]["certainty"] == "clear"]

    def score(idx: list[int]) -> dict:
        yt = [y[i] for i in idx]
        lr = evaluate(yt, [lr_pred[i] for i in idx], lr_top1[idx])
        lr["margin"] = spread(lr_margin[idx])
        lr_ok = [y[i] == lr_pred[i] for i in idx]
        llm_ok = [y[i] == llm_pred[i] for i in idx]
        lr["auroc_top1"], lr["auroc_margin"] = (
            auroc(lr_ok, lr_top1[idx]),
            auroc(lr_ok, lr_margin[idx]),
        )
        llm = evaluate(yt, [llm_pred[i] for i in idx], llm_conf[idx])
        llm["auroc_conf"] = auroc(llm_ok, llm_conf[idx])
        body_acc = float(np.mean([y[i] == lr_body_pred[i] for i in idx]))
        return {
            "n": len(idx),
            "regression": lr,
            "llm": llm,
            "regression_body_only_accuracy": body_acc,
        }

    # Threshold per the plan fixed in 7a8c740.
    perm = np.random.default_rng(SPLIT_SEED).permutation(dedup)
    cal, hold = sorted(perm[: len(perm) // 2]), sorted(perm[len(perm) // 2 :])
    ok = np.array([y[i] == lr_pred[i] for i in range(len(y))])
    t = pick_threshold(lr_margin[cal], ok[cal])
    held = {"threshold": t, "calibration_n": len(cal), "holdout_n": len(hold)}
    if t is not None:
        auto = [i for i in hold if lr_margin[i] >= t]
        held.update(
            holdout_auto_routed=len(auto),
            holdout_auto_accuracy=float(ok[auto].mean()) if auto else None,
            holdout_to_human=len(hold) - len(auto),
        )

    gate = [
        evaluate_task_routing_gate(TaskCategory(llm_pred[i]), float(llm_conf[i]), texts[i])
        for i in range(len(y))
    ]
    per_email = [
        {
            "email_id": labels[i]["email_id"],
            "label": y[i],
            "certainty": labels[i]["certainty"],
            "lr_pred": lr_pred[i],
            "lr_top1": float(lr_top1[i]),
            "lr_margin": float(lr_margin[i]),
            "lr_body_only_pred": lr_body_pred[i],
            "llm_pred": llm_pred[i],
            "llm_conf": float(llm_conf[i]),
            "llm_parse_failed": llm_out[i]["parse_failed"],
            "llm_gate": gate[i].outcome.value,
            "urgent_keyword_hit": is_urgent(texts[i]),
        }
        for i in range(len(y))
    ]
    synthetic = [json.loads(ln) for ln in (HERE / "dataset.jsonl").read_text().splitlines()]
    kw = [
        (r["label"] == "urgent_emergency", is_urgent(r["text"]))
        for r in synthetic
    ]
    result = {
        "counts": {
            "all": len(y),
            "in_scope": len(in_scope),
            "in_scope_dedup": len(dedup),
            "clear": len(clear),
        },
        "in_scope": score(in_scope),
        "in_scope_dedup": score(dedup),
        "clear_only": score(clear),
        "threshold": held,
        "out_of_scope": [p for p in per_email if p["label"] == "out_of_scope"],
        "llm_wrong_but_auto_routed": sum(
            1 for i in in_scope if llm_pred[i] != y[i] and gate[i].outcome.value.startswith("auto")
        ),
        "llm_parse_failures": sum(o["parse_failed"] for o in llm_out),
        "urgent_keywords_on_synthetic": {
            "urgent_emails": sum(u for u, _ in kw),
            "caught": sum(u and h for u, h in kw),
            "false_alarms_on_other_categories": sum(h and not u for u, h in kw),
        },
    }
    (HERE / "real_results.json").write_text(json.dumps(result, indent=2))
    (HERE / "real_predictions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in per_email))
    print(json.dumps(result["counts"]), "threshold", json.dumps(held))


if __name__ == "__main__":
    main()
