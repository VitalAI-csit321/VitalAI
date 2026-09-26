"""Retrain the regression on both synthetic batches and re-measure. Committed before it ran.

Plan, fixed in advance:
- v1 keeps its original split (seed 42, 70/30), so its held-out 135 stay comparable with the
  89.6% in results.json. dataset_v2 is split 70/30 on its own with the same seed.
- One LogisticRegression, same settings as evaluate.py, fitted once on both training halves.
- Report accuracy and per-category recall on each held-out half separately.
- Score the 58 real emails with the new model and apply the same threshold rule as 7a8c740.
  The LLM side reuses real_predictions.jsonl, so no LLM call is made.
- The real-email score is CONTAMINATED: dataset_v2 was written after those emails were seen.
  It is reported as indicative only. The clean measure needs emails nobody here has seen.

    cd backend
    ../../CSIT321_Capstone/backend/.venv/bin/python -m scripts.intent_classifier.evaluate_v2
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from app.rag.embeddings import get_embedding_provider
from scripts.intent_classifier.evaluate import SEED, TEST_SIZE, evaluate, spread
from scripts.intent_classifier.evaluate_real import (
    SPLIT_SEED,
    auroc,
    fetch_emails,
    pick_threshold,
)

HERE = Path(__file__).parent


def load(name: str) -> list[dict]:
    return [json.loads(ln) for ln in (HERE / name).read_text().splitlines()]


def embed(texts: list[str]) -> np.ndarray:
    return np.array(asyncio.run(get_embedding_provider().embed_documents(texts)))


def main() -> None:
    v1, v2 = load("dataset.jsonl"), load("dataset_v2.jsonl")
    tr1, te1 = train_test_split(
        np.arange(len(v1)),
        test_size=TEST_SIZE,
        stratify=[r["label"] for r in v1],
        random_state=SEED,
    )
    tr2, te2 = train_test_split(
        np.arange(len(v2)),
        test_size=TEST_SIZE,
        stratify=[r["label"] for r in v2],
        random_state=SEED,
    )
    e1, e2 = embed([r["text"] for r in v1]), embed([r["text"] for r in v2])
    y1, y2 = [r["label"] for r in v1], [r["label"] for r in v2]

    clf = LogisticRegression(max_iter=5000).fit(
        np.vstack([e1[tr1], e2[tr2]]), [y1[i] for i in tr1] + [y2[i] for i in tr2]
    )

    def score(emb: np.ndarray, y: list[str]) -> tuple[dict, list[str], np.ndarray]:
        proba = clf.predict_proba(emb)
        order = np.argsort(proba, axis=1)
        rows = np.arange(len(y))
        top1 = proba[rows, order[:, -1]]
        margin = top1 - proba[rows, order[:, -2]]
        pred = list(clf.classes_[order[:, -1]])
        out = evaluate(y, pred, top1)
        out["margin"] = spread(margin)
        out["auroc_margin"] = auroc([a == b for a, b in zip(y, pred, strict=True)], margin)
        return out, pred, margin

    synth_v1, _, _ = score(e1[te1], [y1[i] for i in te1])
    synth_v2, _, _ = score(e2[te2], [y2[i] for i in te2])

    labels = load("real_labels.jsonl")
    llm = {p["email_id"]: p for p in load("real_predictions.jsonl")}
    emails = asyncio.run(fetch_emails())
    texts = [
        f"Subject: {emails[lab['email_id']]['subject']}\n\n{emails[lab['email_id']]['body']}"
        for lab in labels
    ]
    y = [lab["label"] for lab in labels]
    in_scope = [i for i, v in enumerate(y) if v != "out_of_scope"]
    emb_real = embed(texts)
    real, pred, margin = score(emb_real[in_scope], [y[i] for i in in_scope])
    llm_acc = float(np.mean([llm[labels[i]["email_id"]]["llm_pred"] == y[i] for i in in_scope]))

    # The threshold rule from 7a8c740, on the same deduplicated split.
    full_pred = dict(zip(in_scope, pred, strict=True))
    full_margin = dict(zip(in_scope, margin, strict=True))
    dedup, seen = [], set()
    for i in in_scope:
        key = emails[labels[i]["email_id"]]["body"].strip().lower()
        if key not in seen:
            seen.add(key)
            dedup.append(i)
    perm = np.random.default_rng(SPLIT_SEED).permutation(dedup)
    cal, hold = sorted(perm[: len(perm) // 2]), sorted(perm[len(perm) // 2 :])
    ok = {i: full_pred[i] == y[i] for i in in_scope}
    t = pick_threshold(np.array([full_margin[i] for i in cal]), np.array([ok[i] for i in cal]))
    held = {"threshold": t, "calibration_n": len(cal), "holdout_n": len(hold)}
    if t is not None:
        auto = [i for i in hold if full_margin[i] >= t]
        held.update(
            holdout_auto_routed=len(auto),
            holdout_auto_accuracy=float(np.mean([ok[i] for i in auto])) if auto else None,
        )
    oos = [i for i, v in enumerate(y) if v == "out_of_scope"]
    oos_margin = [float(m) for m in score(emb_real[oos], ["general_administrative"] * len(oos))[2]]

    joblib.dump(
        {
            "model": clf,
            "labels": list(clf.classes_),
            "trained_on": ["dataset.jsonl", "dataset_v2.jsonl"],
        },
        HERE / "model_v2.joblib",
    )
    (HERE / "results_v2.json").write_text(
        json.dumps(
            {
                "train_size": len(tr1) + len(tr2),
                "synthetic_v1_heldout": synth_v1,
                "synthetic_v2_heldout": synth_v2,
                "real_in_scope_CONTAMINATED": real,
                "real_in_scope_llm_accuracy": llm_acc,
                "real_threshold_CONTAMINATED": held,
                "real_out_of_scope_margins": oos_margin,
                "real_errors": [
                    {
                        "email_id": labels[i]["email_id"],
                        "label": y[i],
                        "pred": full_pred[i],
                        "margin": float(full_margin[i]),
                        "certainty": labels[i]["certainty"],
                    }
                    for i in in_scope
                    if not ok[i]
                ],
            },
            indent=2,
        )
    )
    print(
        f"v1 heldout {synth_v1['accuracy']:.3f} | v2 heldout {synth_v2['accuracy']:.3f} | "
        f"real {real['accuracy']:.3f} (LLM {llm_acc:.3f}) | threshold {held}"
    )


if __name__ == "__main__":
    main()
