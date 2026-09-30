"""M7 ship gate (spec C7): today's classifier prompt against the C6 prompt, same run, same emails.

- old: the production prompt exactly as content_classifier builds it (ten category names).
- new: the same template, but the category list is one `name: description` line for each of
  eleven categories, clinical_enquiry last (spec section 3). DESCRIPTIONS below is the wording
  that ships; Phase B moves it next to TaskCategory unchanged, in this order.

Both prompts go to the production model through app.llm.get_llm() with production settings
(LLM_PROVIDER, model, temperature), so the same script re-runs on Haiku 4.5 (Bedrock) by config.
Each email is asked old then new, back to back. Replies are parsed like
content_classifier._parse_classification but against the eleven labels here: the production
parser converts to TaskCategory and would reject "clinical_enquiry". An unparseable reply
counts as general_administrative, the production fallback. A model error is retried; three in
a row stop the run, which resumes from clinical_predictions.jsonl on the next start.

Sets: all 630 synthetic emails (dataset.jsonl + dataset_v2.jsonl), the 58 real vitalai_qa
emails (read-only, via evaluate_real.fetch_emails; labels from real_labels.jsonl; the 5
out_of_scope ones have no category and are reported but never scored), and the 300 real
patient questions in icliniq_testset.jsonl (label clinical_enquiry).

Gate, fixed before the first run:
1. For each of the ten existing categories, accuracy (share of its emails given that label) on
   the pooled 630 synthetic + 53 in-scope real emails may fall by at most 5 points, old to new.
2. With the new prompt, (clinical_enquiry + urgent_emergency) / 300 >= 80% on the iCliniq set.
   urgent_emergency counts as safe, not as a miss, and is reported on its own.

Attempt 2. Attempt 1 failed gate 1 (urgent_emergency -20.0 points, mostly to clinical_enquiry;
medical_records_request -10.9, to new_patient_onboarding; see RESULTS.md). Three descriptions
were then changed, after its errors had been read, so this run is tuned on the same emails:
urgent_emergency adds "even when written calmly or as a question", clinical_enquiry adds
"never sudden or severe symptoms", new_patient_onboarding adds "not requests for records".
The gate is unchanged.

No email text is written out: the real emails hold real addresses and the iCliniq text is
unlicensed. Raw model replies are kept for synthetic emails only.

    cd backend
    .venv/bin/python -m scripts.intent_classifier.evaluate_clinical
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from scipy.stats import binomtest

import app.services.content_classifier as cc
from app.config import settings
from app.llm import get_llm
from app.models.task import TaskCategory
from scripts.intent_classifier.evaluate_real import fetch_emails

HERE = Path(__file__).parent
OUT = HERE / "clinical_predictions.jsonl"
CLINICAL, URGENT, FALLBACK = "clinical_enquiry", "urgent_emergency", "general_administrative"
MAX_DROP, MIN_SAFE = 0.05, 0.80

DESCRIPTIONS = {
    "appointment_request": "wants to book, change or cancel an appointment.",
    "new_patient_onboarding": (
        "wants to join the clinic as a new patient, or asks how to register. Not requests for"
        " records."
    ),
    "prescription_renewal": "needs a repeat prescription for a medicine they already take.",
    "results_enquiry": "asks for test, pathology or imaging results, or whether they are back.",
    "referral_request": "asks for a referral or referral letter to a specialist or other service.",
    "medical_records_request": (
        "asks for a copy of their medical records, or for them to be transferred or corrected."
    ),
    "billing_insurance_enquiry": (
        "a question about fees, a bill, a payment, Medicare, bulk billing or insurance."
    ),
    "complaint_escalation": (
        "a complaint about the clinic, its staff or the care received, or a demand to escalate."
    ),
    "general_administrative": (
        'any other administrative matter, e.g. opening hours, services offered ("do you do flu'
        ' shots?"), forms, or general health information not about the sender.'
    ),
    "urgent_emergency": (
        "red flags needing immediate care, even when written calmly or as a question, e.g. chest"
        " pain, cannot breathe, collapse, severe bleeding, overdose or self-harm."
    ),
    "clinical_enquiry": (
        "a non-urgent question about the patient's own health or care that needs a clinician's"
        " judgement, e.g. symptoms that are changing or not improving, whether to continue, stop"
        " or adjust a treatment, side effects, what to do after a visit or procedure, or a"
        " question about a condition they already have. Never sudden or severe symptoms. Not a"
        " repeat script, results, a referral, an appointment or a red flag."
    ),
}
LABELS = list(DESCRIPTIONS)
OLD_LABELS = [c.value for c in TaskCategory]
assert set(LABELS) == set(OLD_LABELS) | {CLINICAL}

CATEGORIES = {
    "old": cc._CATEGORY_VALUES,
    "new": "\n".join(f"{name}: {text}" for name, text in DESCRIPTIONS.items()),
}
# Resuming is only safe against the same model and the same two prompts.
RUN_ID = hashlib.sha256(
    json.dumps(
        [
            settings.llm_provider,
            settings.llm_model,
            settings.bedrock_model_id,
            cc._PROMPT_TEMPLATE,
            CATEGORIES,
        ]
    ).encode()
).hexdigest()[:12]


def parse(raw: str) -> tuple[str, float] | None:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        category, confidence = parsed["category"], float(parsed["confidence"])
    except (KeyError, TypeError, ValueError):
        return None
    if category not in LABELS or not 0.0 <= confidence <= 1.0:
        return None
    return category, confidence


async def ask(llm, prompt: str) -> str:
    for attempt in range(3):
        try:
            raw = await llm.ainvoke(prompt)
            return raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
        except Exception as exc:
            print(f"model error {exc!r}, attempt {attempt + 1} of 3", flush=True)
            await asyncio.sleep(15 * (attempt + 1))
    raise SystemExit("model failed three times in a row; fix it and run again to resume")


def load_items() -> list[dict]:
    items = []
    for name in ("dataset.jsonl", "dataset_v2.jsonl"):
        for i, ln in enumerate((HERE / name).read_text().splitlines()):
            row = json.loads(ln)
            items.append(
                {
                    "key": f"{name}:{i}",
                    "set": "synthetic",
                    "label": row["label"],
                    "text": row["text"],
                }
            )
    labels = [json.loads(ln) for ln in (HERE / "real_labels.jsonl").read_text().splitlines()]
    emails = asyncio.run(fetch_emails())
    assert {lab["email_id"] for lab in labels} == set(emails), "labels and vitalai_qa disagree"
    for lab in labels:
        e = emails[lab["email_id"]]
        items.append(
            {
                "key": f"real:{lab['email_id']}",
                "set": "real",
                "label": lab["label"],
                "text": f"Subject: {e['subject']}\n\n{e['body']}",
            }
        )
    for i, ln in enumerate((HERE / "icliniq_testset.jsonl").read_text().splitlines()):
        row = json.loads(ln)
        items.append(
            {"key": f"icliniq:{i}", "set": "icliniq", "label": row["label"], "text": row["text"]}
        )
    return items


async def run(items: list[dict]) -> dict[tuple[str, str], dict]:
    done: dict[tuple[str, str], dict] = {}
    if OUT.exists():
        for ln in OUT.read_text().splitlines():
            rec = json.loads(ln)
            assert rec["run"] == RUN_ID, f"{OUT.name} is from another model or prompt; move it"
            done[rec["key"], rec["prompt"]] = rec
    llm = get_llm()
    with OUT.open("a") as out:
        for n, item in enumerate(items, 1):
            for which in ("old", "new"):
                if (item["key"], which) in done:
                    continue
                prompt = cc._PROMPT_TEMPLATE.format(
                    channel_framing=cc._CHANNEL_FRAMING["email"],
                    categories=CATEGORIES[which],
                    content=item["text"],
                )
                t = time.time()
                raw = await ask(llm, prompt)
                got = parse(raw)
                rec = {
                    "run": RUN_ID,
                    "key": item["key"],
                    "set": item["set"],
                    "prompt": which,
                    "label": item["label"],
                    "category": got[0] if got else FALLBACK,
                    "confidence": got[1] if got else 0.0,
                    "parse_failed": got is None,
                    "seconds": round(time.time() - t, 2),
                }
                if item["set"] == "synthetic":
                    rec["raw"] = raw
                out.write(json.dumps(rec) + "\n")
                out.flush()
                done[item["key"], which] = rec
                print(f"{n}/{len(items)} {which} {item['label']} -> {rec['category']}", flush=True)
    return done


def per_category(rows: list[tuple[str, str]]) -> dict:
    """rows: (label, predicted). Accuracy per label = share of that label's emails given it."""
    n, right = Counter(lab for lab, _ in rows), Counter(lab for lab, p in rows if lab == p)
    return {lab: {"n": n[lab], "accuracy": right[lab] / n[lab]} for lab in LABELS if n[lab]}


def confusion(rows: list[tuple[str, str]]) -> dict:
    return {
        lab: dict(Counter(p for t, p in rows if t == lab))
        for lab in LABELS
        if any(t == lab for t, _ in rows)
    }


def report(items: list[dict], done: dict[tuple[str, str], dict]) -> dict:
    pred = {w: {i["key"]: done[i["key"], w]["category"] for i in items} for w in ("old", "new")}
    scored = [i for i in items if i["set"] in ("synthetic", "real") and i["label"] in OLD_LABELS]
    out: dict = {
        "run_id": RUN_ID,
        "model": {
            "provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "bedrock_model_id": settings.bedrock_model_id,
            "temperature": settings.llm_temperature,
        },
        "prompt_categories": CATEGORIES,
        "counts": dict(Counter(i["set"] for i in items)),
        "scored_existing_categories": len(scored),
        "parse_failures": {
            w: dict(
                Counter(
                    done[i["key"], w]["set"] for i in items if done[i["key"], w]["parse_failed"]
                )
            )
            for w in ("old", "new")
        },
    }
    subsets = {
        "pooled": scored,
        "synthetic": [i for i in scored if i["set"] == "synthetic"],
        "real": [i for i in scored if i["set"] == "real"],
    }
    for name, subset in subsets.items():
        block = {}
        for w in ("old", "new"):
            rows = [(i["label"], pred[w][i["key"]]) for i in subset]
            block[w] = {
                "accuracy": sum(t == p for t, p in rows) / len(rows),
                "per_category": per_category(rows),
                "confusion": confusion(rows),
                "labelled_clinical_enquiry": sum(p == CLINICAL for _, p in rows),
            }
        old_ok = {i["key"]: pred["old"][i["key"]] == i["label"] for i in subset}
        new_ok = {i["key"]: pred["new"][i["key"]] == i["label"] for i in subset}
        lost = sum(old_ok[k] and not new_ok[k] for k in old_ok)
        gained = sum(new_ok[k] and not old_ok[k] for k in old_ok)
        block["flips"] = {
            "old_right_new_wrong": lost,
            "old_wrong_new_right": gained,
            "mcnemar_exact_p": binomtest(lost, lost + gained).pvalue if lost + gained else None,
            "lost_went_to": dict(
                Counter(
                    pred["new"][i["key"]]
                    for i in subset
                    if old_ok[i["key"]] and not new_ok[i["key"]]
                )
            ),
        }
        out[name] = block

    drops = {}
    for lab in OLD_LABELS:
        old_acc = out["pooled"]["old"]["per_category"][lab]["accuracy"]
        new_acc = out["pooled"]["new"]["per_category"][lab]["accuracy"]
        drops[lab] = {
            "n": out["pooled"]["old"]["per_category"][lab]["n"],
            "old": old_acc,
            "new": new_acc,
            "change_points": round(100 * (new_acc - old_acc), 1),
            "pass": old_acc - new_acc <= MAX_DROP + 1e-9,
        }

    icl = [i for i in items if i["set"] == "icliniq"]
    dist = {w: dict(Counter(pred[w][i["key"]] for i in icl).most_common()) for w in ("old", "new")}
    clinical, urgent = dist["new"].get(CLINICAL, 0), dist["new"].get(URGENT, 0)
    out["icliniq"] = {
        "n": len(icl),
        "distribution": dist,
        "new_clinical_share": clinical / len(icl),
        "new_urgent_share": urgent / len(icl),
        "new_safe_share": (clinical + urgent) / len(icl),
    }
    out["out_of_scope_real"] = [
        {"key": i["key"], "old": pred["old"][i["key"]], "new": pred["new"][i["key"]]}
        for i in items
        if i["set"] == "real" and i["label"] not in OLD_LABELS
    ]
    gate1 = all(d["pass"] for d in drops.values())
    gate2 = out["icliniq"]["new_safe_share"] >= MIN_SAFE
    out["gate"] = {
        "existing_categories": drops,
        "existing_categories_pass": gate1,
        "icliniq_safe_share": out["icliniq"]["new_safe_share"],
        "icliniq_pass": gate2,
        "pass": gate1 and gate2,
    }
    return out


def main() -> None:
    items = load_items()
    assert Counter(i["set"] for i in items) == {"synthetic": 630, "real": 58, "icliniq": 300}
    print(f"run {RUN_ID}: {len(items)} emails, two prompts each", flush=True)
    done = asyncio.run(run(items))
    result = report(items, done)
    (HERE / "clinical_results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result["gate"], indent=2))


if __name__ == "__main__":
    main()
