"""Generate a labelled synthetic email dataset with the local Ollama model.

The label is chosen first and the model is asked to write an email for it, so the
label is ground truth by construction. The model never labels existing text.

Resumable: re-running tops each category up to PER_CATEGORY from dataset.jsonl.

    cd backend
    ../../CSIT321_Capstone/backend/.venv/bin/python -m scripts.intent_classifier.generate
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from app.config import settings

OUT = Path(__file__).with_name("dataset.jsonl")
PER_CATEGORY = 45
MAX_TRIES = 4

SCENARIOS: dict[str, list[str]] = {
    "appointment_request": [
        "book a new appointment with their usual GP",
        "reschedule an existing appointment to another day",
        "cancel an appointment they cannot make",
        "ask for the earliest available appointment for a non-urgent issue",
        "book a telehealth appointment instead of coming in",
        "book a longer appointment to discuss several ongoing issues",
        "book an appointment for their child for a routine check",
        "ask whether a particular doctor has any openings next week",
    ],
    "new_patient_onboarding": [
        "ask if the clinic is taking new patients after moving to the area",
        "ask what forms and documents they need to register as a new patient",
        "ask how to transfer their family to this clinic from their old GP",
        "ask whether they can register before their first visit",
        "say they are new in town and want to join the practice",
        "ask if the clinic bulk bills new patients and how to sign up",
        "ask how to register a newborn baby at the practice",
    ],
    "prescription_renewal": [
        "request a repeat prescription for blood pressure medication",
        "say they are running out of their regular medication and need a new script",
        "ask for an e-script to be sent to their phone for an ongoing medication",
        "ask whether a renewal of their contraceptive pill needs an appointment",
        "ask for their asthma inhaler script to be renewed",
        "say their pharmacy told them the script has no repeats left",
        "ask for a repeat of their cholesterol tablets before going overseas",
    ],
    "results_enquiry": [
        "ask whether their blood test results have come back",
        "ask what their recent X-ray or scan results mean",
        "ask why nobody has called about their biopsy results",
        "ask if they need an appointment to discuss test results",
        "ask for a copy of their pathology results to be sent to them",
        "say they got a text to call about results and want to know more",
        "ask about the results of their child's urine test",
    ],
    "referral_request": [
        "ask for a referral to a dermatologist",
        "say their specialist referral has expired and needs renewing",
        "ask for a referral to a physiotherapist after an injury",
        "ask for a mental health care plan and a psychologist referral",
        "ask for a referral letter to be sent to a named cardiologist",
        "ask whether they need a new referral to keep seeing their specialist",
        "ask for a referral for an MRI requested by their chiropractor",
    ],
    "medical_records_request": [
        "ask for a copy of their full medical history",
        "ask for their records to be transferred to a new clinic interstate",
        "ask for their vaccination history for a new job",
        "ask for records to be sent to their lawyer or insurer with consent",
        "ask how to access their records from years ago",
        "ask for a copy of a discharge summary the clinic received",
        "ask for their child's immunisation record for school enrolment",
    ],
    "billing_insurance_enquiry": [
        "query an unexpected gap fee on their bill",
        "ask whether a service is bulk billed",
        "ask why their Medicare rebate has not come through",
        "ask for an itemised invoice for their private health insurer",
        "say they were charged twice for one appointment",
        "ask about fees for a WorkCover or TAC related visit",
        "ask for a payment plan for an outstanding bill",
    ],
    "complaint_escalation": [
        "complain about rude treatment by reception staff",
        "complain about waiting over an hour past their appointment time",
        "complain that a doctor dismissed their concerns",
        "complain that their privacy was breached in the waiting room",
        "escalate a complaint that was ignored last time and ask for the practice manager",
        "complain that a prescription error was made",
        "complain that nobody returned their calls for a week",
    ],
    "general_administrative": [
        "ask about the clinic's opening hours over the public holiday",
        "ask where to park near the clinic",
        "update their home address and phone number",
        "ask whether the clinic has wheelchair access",
        "ask whether the clinic can email a form to their employer",
        "ask whether the clinic offers flu vaccines this season and when",
        "ask if there is an interpreter service available",
        "ask how to change their contact email on file",
    ],
    "urgent_emergency": [
        "report sudden chest pain and shortness of breath happening now",
        "say their child has a very high fever and is hard to wake",
        "report heavy bleeding that will not stop",
        "say they have taken too many tablets and feel unwell",
        "report sudden weakness on one side of the face and slurred speech",
        "say an elderly parent has fallen and cannot get up",
        "report a severe allergic reaction with swelling of the throat",
    ],
}

LENGTHS = [
    "one short line, fewer than 20 words",
    "two or three sentences",
    "one medium paragraph",
    "several paragraphs with background detail",
]
REGISTERS = [
    "polite and formal",
    "blunt and terse",
    "anxious and worried",
    "angry and frustrated",
    "casual and chatty",
]
SENDERS = [
    "the patient",
    "the patient",
    "a parent writing about their child",
    "an adult child writing about an elderly parent",
]
NAMES = [
    "Priya Sharma",
    "Tom Nguyen",
    "Grace O'Connor",
    "Ahmed Hassan",
    "Lucy Chen",
    "Ben Walker",
    "Maria Rossi",
    "Jack Taylor",
    "Aroha Wiremu",
    "Sam Patel",
    "Olivia Brown",
    "Hiro Tanaka",
]
_PREAMBLE = re.compile(r"^(sure|okay|here('s| is)|certainly)\b.*$", re.IGNORECASE)


def _ollama(prompt: str, seed: int) -> str:
    body = json.dumps(
        {
            "model": settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.9, "seed": seed, "num_predict": 600},
        }
    ).encode()
    req = urllib.request.Request(
        f"{settings.ollama_base_url}/api/generate", body, {"Content-Type": "application/json"}
    )
    for attempt in range(3):  # Ollama answered a transient 500 once, 267 rows into a run
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())["response"]
        except urllib.error.HTTPError:
            if attempt == 2:
                raise
            time.sleep(5)
    raise AssertionError("unreachable")


def _clean(raw: str) -> str:
    lines = [ln.rstrip() for ln in raw.strip().splitlines()]
    while lines and (
        not lines[0].strip()
        or _PREAMBLE.match(lines[0].strip())
        or lines[0].lower().startswith("subject:")
        or lines[0].startswith("#")
    ):
        lines.pop(0)
    text = "\n".join(lines).strip().replace("**", "")
    return text.strip('"').strip()


def _fill_placeholders(text: str, rng: random.Random, name: str) -> tuple[str, int]:
    """gemma2:2b writes "[Parent's name]" into most formal emails despite being told not to.
    Rejecting those would silently drop the long formal register, so fill them instead."""

    def fill(m: re.Match[str]) -> str:
        inner = m.group(1).lower()
        if re.search(r"doctor|dr\b|gp|clinic|practice|receptionist|manager", inner):
            return rng.choice(["Dr Lee", "Dr Patel", "the clinic", "Dr Morrison"])
        if "name" in inner:
            return name.split()[0] if rng.random() < 0.5 else name
        if re.search(r"date|time|day|when", inner):
            return rng.choice(
                ["last Tuesday", "yesterday", "12 August", "this morning", "two weeks ago"]
            )
        if re.search(r"phone|number", inner):
            return "0412 345 678"
        if re.search(r"address", inner):
            return "14 Smith Street, Wollongong"
        if len(inner.split()) <= 3:
            return m.group(1)
        return "\x00"  # too specific to guess; caller rejects the email

    filled, n = re.subn(r"\[([^\]]*)\]", fill, text)
    return re.sub(r"\bDr\.? (?=Dr )", "", filled), n


def _add_typos(text: str, rng: random.Random) -> str:
    """Lowercase, drop most punctuation, swap letters in ~6% of words."""
    text = re.sub(r"[.,;:'!]", lambda m: "" if rng.random() < 0.7 else m.group(), text.lower())
    words = text.split(" ")
    for i, w in enumerate(words):
        if len(w) > 3 and rng.random() < 0.06:
            j = rng.randrange(len(w) - 1)
            words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
    return " ".join(words)


def _make_one(label: str, idx: int) -> dict | None:
    rng = random.Random(f"{label}:{idx}")
    scenario = rng.choice(SCENARIOS[label])
    length, register, sender = rng.choice(LENGTHS), rng.choice(REGISTERS), rng.choice(SENDERS)
    signed = rng.random() < 0.6
    name = rng.choice(NAMES)
    # An email that reports an emergency is urgent whatever else it says, so an emergency can
    # never be the minor matter: labelling it anything else would be wrong by construction.
    minor = [c for c in SCENARIOS if c not in (label, "urgent_emergency")]
    secondary = rng.choice(minor) if rng.random() < 0.15 else None
    typos = rng.random() < 0.25
    identity = f"Sign it as {name}." if signed else "Do not sign it and do not give any name."
    extra = (
        f" Its main purpose is the request above, but it also briefly mentions a second, "
        f"minor matter: {rng.choice(SCENARIOS[secondary])}."
        if secondary
        else ""
    )
    prompt = (
        f"Write the body of an email that {sender} sends to their GP clinic in Australia. "
        f"The sender wants to {scenario}.{extra} Tone: {register}. Length: {length}. {identity} "
        "Write ONLY the email body. No subject line, no explanation, no placeholders in square "
        "brackets, no markdown."
    )
    for attempt in range(MAX_TRIES):
        text, n_filled = _fill_placeholders(
            _clean(_ollama(prompt, seed=idx * 10 + attempt)), rng, name
        )
        if len(text) >= 10 and "\x00" not in text and "[" not in text:
            break
    else:
        return None
    if typos:
        text = _add_typos(text, rng)
    notes = (
        f"scenario={scenario}; length={length}; register={register}; sender={sender}; "
        f"signed={signed}; typos={typos}; placeholders_filled={n_filled}"
    )
    if secondary:
        notes += f"; MULTI-INTENT: dominant={label}, secondary={secondary}"
    return {"text": text, "label": label, "notes": notes}


def main() -> None:
    from app.models.task import TaskCategory

    assert list(SCENARIOS) == [c.value for c in TaskCategory], "labels drifted from TaskCategory"
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
