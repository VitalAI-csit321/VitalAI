"""A TEST set of real patient-written health questions for the clinical_enquiry category (M7).

Used only to measure whether the production classifier recognises real clinical enquiries
(M7 ship gate C7: at least 80% recall). Never used as training data. It measures whatever
model the classifier runs on, so it stays valid after the move to Claude Haiku 4.5.

Source: the chatdoctor_icliniq config of the Hugging Face bundle
Malikeh1375/medical-question-answering-datasets, pinned to REVISION below. The bundle is
labelled MIT, but its ChatDoctor text was scraped from iCliniq, whose owners never licensed it.
So the raw text is NOT committed: this script downloads, filters and writes a local,
gitignored file (icliniq_testset.jsonl). Only this script is committed.

Filter, fixed before any classifier has been run on the data:
- body 60 to 1200 characters after trimming;
- not urgent by the project's own is_urgent(): a red-flag message is urgent_emergency, not a
  clinical enquiry, under the M7 definition;
- not obviously another category (repeat/refill, referral, appointment/booking, certificate,
  results not yet received);
- deduplicated on lowercased text.
The forum opener ("Hello doctor,") is replaced by a greeting drawn from a pool and each record
gets a generic subject, so the text reads like mail to a clinic. Then SAMPLE records are drawn
with a fixed seed, so every run and every model is scored on the same questions.

Paged through the datasets-server JSON API (100 rows a page, a pause between pages, waits and
retries on HTTP 429): the bundle is Parquet, and reading Parquet would add pyarrow.

    cd backend
    ../../CSIT321_Capstone/backend/.venv/bin/python -m scripts.intent_classifier.fetch_icliniq
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.services.triage_service import is_urgent

DATASET = "Malikeh1375/medical-question-answering-datasets"
CONFIG = "chatdoctor_icliniq"
REVISION = "29833779cb5921f474d9f469aa85c115277bf489"
OUT = Path(__file__).with_name("icliniq_testset.jsonl")
SEED = 20260930
SAMPLE = 300
PAUSE_S = 1.0

OTHER_CATEGORY = re.compile(
    r"\b(repeat (prescription|script)|refill|referral|refer me|appointment|book(ing)? (a|an)\b"
    r"|medical certificate|sick note|haven.t (got|received) my (results|report))",
    re.IGNORECASE,
)
OPENER = re.compile(r"^\s*(hello|hi|hey|dear)\s+(doctor|doc|sir|madam|dr\.?)\s*[,.!]*\s*", re.I)
GREETINGS = ["Hi", "Hello", "Dear Doctor", "Hi Dr Raman", "Hello Dr Whitfield", "Good morning", ""]
SUBJECTS = ["Question", "Quick question", "Hi", "Help please", "Enquiry", "Query", "Follow up"]


def _get(url: str) -> dict:
    for attempt in range(8):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=60).read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            wait = int(exc.headers.get("Retry-After") or 0) or min(60, 5 * 2**attempt)
            print(f"rate limited, waiting {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit("still rate limited after 8 tries; run again later")


def _rows() -> list[str]:
    info = _get(f"https://huggingface.co/api/datasets/{DATASET}")
    if info["sha"] != REVISION:
        raise SystemExit(f"{DATASET} moved from {REVISION} to {info['sha']}; re-check before use")
    out: list[str] = []
    while True:
        page = _get(
            "https://datasets-server.huggingface.co/rows"
            f"?dataset={DATASET}&config={CONFIG}&split=train&offset={len(out)}&length=100"
        )
        rows = page.get("rows", [])
        out += [r["row"]["input"] for r in rows]
        if not rows or len(out) >= page["num_rows_total"]:
            return out
        time.sleep(PAUSE_S)


def main() -> None:
    rng = random.Random(SEED)
    raw = _rows()
    kept, seen = [], set()
    dropped = {"length": 0, "urgent": 0, "other_category": 0, "duplicate": 0}
    for text in raw:
        body = " ".join(text.split())
        if not 60 <= len(body) <= 1200:
            dropped["length"] += 1
        elif is_urgent(body):
            dropped["urgent"] += 1
        elif OTHER_CATEGORY.search(body):
            dropped["other_category"] += 1
        elif body.lower() in seen:
            dropped["duplicate"] += 1
        else:
            seen.add(body.lower())
            kept.append(body)
    sample = rng.sample(kept, min(SAMPLE, len(kept)))
    records = []
    for body in sample:
        greeting = rng.choice(GREETINGS)
        body = OPENER.sub("", body)
        records.append(
            {
                "text": f"Subject: {rng.choice(SUBJECTS)}\n\n"
                + (f"{greeting},\n\n{body}" if greeting else body),
                "label": "clinical_enquiry",
                "notes": f"source={DATASET}@{REVISION[:12]}/{CONFIG}; test only, never train",
            }
        )
    OUT.write_text("".join(json.dumps(r) + "\n" for r in records))
    print(f"downloaded {len(raw)}, passed filter {len(kept)}, dropped {dropped}")
    print(f"wrote {len(records)} test records to {OUT.name}")


if __name__ == "__main__":
    main()
