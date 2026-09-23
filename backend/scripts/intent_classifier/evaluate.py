"""Train a logistic regression over nomic embeddings and compare it with the LLM classifier.

Fit once, on a fixed stratified split. Nothing here is tuned against the test set.
Offline only: no database, no guardrail, nothing wired into the app.

    cd backend
    ../../CSIT321_Capstone/backend/.venv/bin/python -m scripts.intent_classifier.evaluate
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

import app.services.content_classifier as cc
from app.config import settings
from app.llm.provider import get_llm
from app.models.task import TaskCategory
from app.rag.embeddings import get_embedding_provider

HERE = Path(__file__).parent
LABELS = [c.value for c in TaskCategory]
SEED = 42
TEST_SIZE = 0.3


def spread(values: np.ndarray) -> dict:
    uniq, counts = np.unique(np.round(values, 4), return_counts=True)
    return {
        "n": int(values.size),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "p10": float(np.percentile(values, 10)),
        "p50": float(np.percentile(values, 50)),
        "p90": float(np.percentile(values, 90)),
        "distinct_values": int(uniq.size),
        "most_common": [
            [float(v), int(c)]
            for v, c in sorted(zip(uniq, counts, strict=True), key=lambda t: -t[1])[:5]
        ],
    }


def evaluate(y_true: list[str], y_pred: list[str], conf: np.ndarray) -> dict:
    correct = np.array([t == p for t, p in zip(y_true, y_pred, strict=True)])
    hi, lo = settings.task_routing_auto_threshold, settings.task_routing_floor
    bands = {
        f"auto (>={hi:.2f})": conf >= hi,
        f"flagged ({lo:.2f}-{hi:.2f})": (conf >= lo) & (conf < hi),
        f"human (<{lo:.2f})": conf < lo,
    }
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    assert cm.sum() == len(y_true)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "report": classification_report(
            y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0
        ),
        "confusion_matrix": cm.tolist(),
        "confidence": spread(conf),
        # If the number measures anything, right answers score higher than wrong ones.
        "mean_conf_when_correct": float(conf[correct].mean()) if correct.any() else None,
        "mean_conf_when_wrong": float(conf[~correct].mean()) if (~correct).any() else None,
        "gate_bands": {
            name: {"count": int(m.sum()), "accuracy": float(correct[m].mean()) if m.any() else None}
            for name, m in bands.items()
        },
    }


async def run_llm(texts: list[str]) -> list[dict]:
    llm = get_llm()
    out = []
    for i, text in enumerate(texts):
        prompt = cc._PROMPT_TEMPLATE.format(
            channel_framing=cc._CHANNEL_FRAMING["email"],
            categories=cc._CATEGORY_VALUES,
            content=text,
        )
        raw = await llm.ainvoke(prompt)
        raw = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
        rec = {"raw": raw, "fenced": raw.strip().startswith("```")}
        try:
            # The production parser, which already tolerates the ```json fence.
            category, confidence = cc._parse_classification(raw)
            rec.update(category=category.value, confidence=confidence, parse_failed=False)
        except cc.ClassificationParseError:
            # Exactly what classify_content() falls back to.
            rec.update(category="general_administrative", confidence=0.0, parse_failed=True)
        out.append(rec)
        print(f"llm {i + 1}/{len(texts)} {rec['category']} {rec['confidence']}", flush=True)
    return out


def main() -> None:
    rows = [json.loads(ln) for ln in (HERE / "dataset.jsonl").read_text().splitlines()]
    texts, y = [r["text"] for r in rows], [r["label"] for r in rows]

    t = time.time()
    emb = np.array(asyncio.run(get_embedding_provider().embed_documents(texts)))  # one batched call
    print(f"G2 embedded {emb.shape[0]} vectors, dim {emb.shape[1]}, {time.time() - t:.1f}s")

    idx = np.arange(len(rows))
    tr, te = train_test_split(idx, test_size=TEST_SIZE, stratify=y, random_state=SEED)
    y_tr, y_te = [y[i] for i in tr], [y[i] for i in te]
    assert set(y_tr) == set(y_te) == set(LABELS), "a category is missing from one half of the split"

    clf = LogisticRegression(max_iter=5000).fit(emb[tr], y_tr)
    proba = clf.predict_proba(emb[te])
    order = np.argsort(proba, axis=1)
    top1 = proba[np.arange(len(te)), order[:, -1]]
    margin = top1 - proba[np.arange(len(te)), order[:, -2]]
    lr_pred = list(clf.classes_[order[:, -1]])
    lr = evaluate(y_te, lr_pred, top1)
    lr["margin"] = spread(margin)
    print(f"G3 regression accuracy {lr['accuracy']:.3f}")

    llm_out = asyncio.run(run_llm([texts[i] for i in te]))
    llm_conf = np.array([r["confidence"] for r in llm_out])
    llm = evaluate(y_te, [r["category"] for r in llm_out], llm_conf)
    llm["parse_failures"] = sum(r["parse_failed"] for r in llm_out)
    llm["fenced_responses"] = sum(r["fenced"] for r in llm_out)
    print(f"G4 llm accuracy {llm['accuracy']:.3f}, parse failures {llm['parse_failures']}")

    joblib.dump(
        {
            "model": clf,
            "labels": list(clf.classes_),
            "embedding": "nomic-ai/nomic-embed-text-v1",
            "dim": int(emb.shape[1]),
            "document_prefix": "search_document: ",
        },
        HERE / "model.joblib",
    )
    per_item = [
        {
            "row": int(i),
            "label": y[i],
            "lr_pred": p,
            "lr_top1": float(c),
            "lr_margin": float(m),
            "llm_pred": o["category"],
            "llm_conf": o["confidence"],
            "llm_parse_failed": o["parse_failed"],
            "llm_raw": o["raw"],
        }
        for i, p, c, m, o in zip(te, lr_pred, top1, margin, llm_out, strict=True)
    ]
    (HERE / "test_predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in per_item))
    (HERE / "results.json").write_text(
        json.dumps(
            {
                "dataset_size": len(rows),
                "train_size": len(tr),
                "test_size": len(te),
                "seed": SEED,
                "labels": LABELS,
                "embedding_shape": list(emb.shape),
                "llm_model": settings.llm_model,
                "llm_temperature": settings.llm_temperature,
                "regression": lr,
                "llm": llm,
            },
            indent=2,
        )
    )
    print("wrote model.joblib, results.json, test_predictions.jsonl")


if __name__ == "__main__":
    main()
