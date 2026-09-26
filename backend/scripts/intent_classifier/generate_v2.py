"""Second synthetic batch, covering what the first one lacked. Written AFTER the real-email
run (7a8c740, 2446ada), so it is not independent of that test set; see RESULTS.md.

Adds, per email: a subject line (production classifies "Subject: ...\\n\\nbody"), a
"single short question" length, ~8% in another language, ~10% with a quoted reply chain.
Scenarios drawn up because of a real-mail failure are tagged `informed_by_real_test=True`.

    cd backend
    ../../CSIT321_Capstone/backend/.venv/bin/python -m scripts.intent_classifier.generate_v2
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from scripts.intent_classifier.generate import (
    MAX_TRIES,
    NAMES,
    REGISTERS,
    SCENARIOS,
    SENDERS,
    _add_typos,
    _clean,
    _fill_placeholders,
    _ollama,
)

OUT = Path(__file__).with_name("dataset_v2.jsonl")
PER_CATEGORY = 18

# (scenario, informed_by_real_test)
EXTRA: dict[str, list[tuple[str, bool]]] = {
    "appointment_request": [
        ("ask whether any doctor is free to see them on a particular day", True),
        ("ask if they can come in and see a GP sometime this week", True),
        ("ask what times are free for a check-up", False),
    ],
    "new_patient_onboarding": [
        ("ask whether they can become a patient and see a doctor soon", False),
        ("ask if the practice accepts international students as new patients", False),
    ],
    "prescription_renewal": [
        ("ask the doctor to send a new script for their regular medicine to their pharmacy", False),
        ("ask if they can get more of their usual tablets without coming in", False),
    ],
    "results_enquiry": [
        ("ask if the doctor has looked at their scan yet", False),
        ("ask whether hearing nothing about their tests means everything is fine", False),
    ],
    "referral_request": [
        ("ask the GP to refer them to a specialist a friend recommended", False),
        ("ask whether they need a referral before booking a psychologist", False),
    ],
    "medical_records_request": [
        ("ask for their records to be sent to their new GP", False),
        ("ask for a letter summarising their medical history for travel insurance", False),
    ],
    "billing_insurance_enquiry": [
        ("ask how much a standard consultation costs", False),
        ("ask whether they can pay an outstanding bill online", False),
    ],
    "complaint_escalation": [
        ("complain about being charged for an appointment the clinic cancelled", False),
        ("complain that their test results were given to the wrong person", False),
        ("complain that a receptionist discussed their health loudly in front of others", False),
        ("complain that the doctor ran very late and then rushed the appointment", False),
    ],
    "general_administrative": [
        ("ask for a list of the clinic's doctors and what each one specialises in", True),
        ("ask how to find the clinic and which entrance to use", False),
        ("ask whether a female doctor works at the clinic", False),
        ("ask what time the clinic closes on Friday", False),
    ],
    "urgent_emergency": [
        ("say their partner is suddenly confused and cannot speak properly", False),
        ("say their toddler has just swallowed a button battery", False),
        ("say they are having thoughts of ending their life", False),
        ("say their child had a fit and is still very drowsy", False),
    ],
}
LENGTHS = [
    "a single short question of fewer than 12 words",
    "a single short question of fewer than 12 words",
    "two or three sentences",
    "one medium paragraph",
]
LANGUAGES = ["Dutch", "Vietnamese", "Mandarin Chinese", "Arabic", "Hindi", "Spanish"]


def _split_subject(raw: str) -> tuple[str, str]:
    lines = raw.strip().splitlines()
    for i, ln in enumerate(lines[:3]):
        if ln.lower().lstrip("*# ").startswith("subject:"):
            subject = ln.split(":", 1)[1].strip().strip("*").strip()
            return subject, "\n".join(lines[i + 1 :])
    return "", raw


def _make_one(label: str, idx: int) -> dict | None:
    rng = random.Random(f"v2:{label}:{idx}")
    pool = [(s, False) for s in SCENARIOS[label]] + EXTRA[label]
    # Half from the new scenarios, so they are not drowned by the originals.
    scenario, informed = rng.choice(EXTRA[label]) if rng.random() < 0.5 else rng.choice(pool)
    length, register, sender = rng.choice(LENGTHS), rng.choice(REGISTERS), rng.choice(SENDERS)
    signed = rng.random() < 0.5
    name = rng.choice(NAMES)
    language = rng.choice(LANGUAGES) if rng.random() < 0.08 else None
    typos = language is None and rng.random() < 0.25
    reply_chain = rng.random() < 0.10
    identity = f"Sign it as {name}." if signed else "Do not sign it and do not give any name."
    lang = f" Write the whole email, subject included, in {language}." if language else ""
    prompt = (
        f"Write an email that {sender} sends to their GP clinic in Australia. "
        f"The sender wants to {scenario}. Tone: {register}. Length of the body: {length}. "
        f"{identity}{lang} The first line must be 'Subject: ' followed by a short subject the "
        "sender would plausibly type. Then the body. No explanation, no placeholders in square "
        "brackets, no markdown."
    )
    for attempt in range(MAX_TRIES):
        subject, body = _split_subject(_ollama(prompt, seed=50_000 + idx * 10 + attempt))
        body, n_filled = _fill_placeholders(_clean(body), rng, name)
        subject, _ = _fill_placeholders(subject, rng, name)
        if subject and len(body) >= 5 and "\x00" not in body + subject and "[" not in body:
            break
    else:
        return None
    if typos:
        body = _add_typos(body, rng)
    if reply_chain:
        body += f"\n\nOn Mon, 3 Aug 2026 at 09:12, {name} wrote:\n> " + body.replace("\n", "\n> ")
    notes = (
        f"scenario={scenario}; informed_by_real_test={informed}; length={length}; "
        f"register={register}; sender={sender}; signed={signed}; typos={typos}; "
        f"language={language or 'English'}; reply_chain={reply_chain}; "
        f"placeholders_filled={n_filled}"
    )
    return {"text": f"Subject: {subject}\n\n{body}", "label": label, "notes": notes}


def main() -> None:
    existing = [json.loads(ln) for ln in OUT.read_text().splitlines()] if OUT.exists() else []
    seen = {r["text"].strip().lower() for r in existing}
    counts = Counter(r["label"] for r in existing)
    with OUT.open("a") as fh:
        for label in SCENARIOS:
            idx = counts[label]
            attempts = 0
            while counts[label] < PER_CATEGORY and attempts < PER_CATEGORY * 3:
                rec = _make_one(label, idx)
                idx += 1
                attempts += 1
                if rec is None or rec["text"].strip().lower() in seen:
                    continue
                seen.add(rec["text"].strip().lower())
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                counts[label] += 1
                print(label, counts[label], flush=True)
    for label in SCENARIOS:
        print(f"{label:28s} {counts[label]}")


if __name__ == "__main__":
    main()
