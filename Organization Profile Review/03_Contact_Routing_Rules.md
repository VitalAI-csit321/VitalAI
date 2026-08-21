<!-- doc_type: routing_rules | access_scope: sensitive -->

# Contact Routing Rules

Internal document. Grounds routing behaviour. Never surfaced to patients. Rewritten 2026-08-17 against the real routing code (`app/models/task.py::TaskCategory`, `app/services/task_routing_rules.py`, `app/services/task_routing_gate.py`) — earlier revisions described a three-axis category/urgency/action-risk model with an invented 85-point HITL gate. Neither exists. This revision states the real mechanism.

## Routing Model

An incoming email or call is classified into one of ten fixed categories, then a single confidence score decides whether it auto-routes, auto-routes but gets flagged for audit sampling, or goes straight to human review. There is no separate urgency axis and no action-risk tier — category and confidence are the whole model.

## Task Categories

`TaskCategory` is a real Postgres enum with exactly these ten values — the classifier's output is constrained to this set, it is not freeform text matched against a table. None of the earlier freeform categories (booking/general/registration/referral/document/billing/clinical/prescription/emergency/consent/fallback) are real category tokens; a routing-table row for one of them could never actually be produced by a classification call. Where an earlier category had no clean match, it's folded into the nearest real one below rather than expanding the enum (a real schema + classifier-prompt change, out of scope for this reconciliation).

| Category | Example | Folded from |
| --- | --- | --- |
| `APPOINTMENT_REQUEST` | "I want to book an appointment" | booking |
| `NEW_PATIENT_ONBOARDING` | "I want to register as a new patient" | registration |
| `PRESCRIPTION_RENEWAL` | "Can I renew my prescription?" | prescription |
| `RESULTS_ENQUIRY` | "Can you explain my test result?" | clinical question |
| `REFERRAL_REQUEST` | "I need a referral" | referral |
| `MEDICAL_RECORDS_REQUEST` | "I want a copy of my records" | document upload |
| `BILLING_INSURANCE_ENQUIRY` | "How much do I pay?" / "There's a problem with my payment" | billing (query and dispute both — no split) |
| `COMPLAINT_ESCALATION` | "I want to make a complaint" / a consent dispute | consent issue (disputed), general complaint |
| `GENERAL_ADMINISTRATIVE` | "What are your opening hours?" | general enquiry, consent issue (routine, non-disputed) |
| `URGENT_EMERGENCY` | "I feel very unwell" / "I can't breathe" | urgent health concern, emergency language |

There is no separate "fallback" category. A message the classifier can't confidently place still gets its best-guess category, and low confidence on that guess is what sends it to human review (see gate below) — the fallback behaviour lives in the confidence threshold, not a category value.

## Category-to-Role Routing Table

Each category maps to exactly one role's queue — a direct lookup (`app/services/task_routing_rules.py::resolve_target_role`), not a multi-step handoff. A referral is not "operator then doctor"; it routes to `OPERATOR` only. Billing is not split between a query and a dispute; every `BILLING_INSURANCE_ENQUIRY` routes to `FRONT_DESK`.

| Category | Route to |
| --- | --- |
| `APPOINTMENT_REQUEST` | `FRONT_DESK` |
| `NEW_PATIENT_ONBOARDING` | `FRONT_DESK` |
| `PRESCRIPTION_RENEWAL` | `DOCTOR` |
| `RESULTS_ENQUIRY` | `DOCTOR` |
| `REFERRAL_REQUEST` | `OPERATOR` |
| `MEDICAL_RECORDS_REQUEST` | `OPERATOR` |
| `BILLING_INSURANCE_ENQUIRY` | `FRONT_DESK` |
| `COMPLAINT_ESCALATION` | `OPERATOR` |
| `GENERAL_ADMINISTRATIVE` | `FRONT_DESK` |
| `URGENT_EMERGENCY` | `OPERATOR` |

## The Routing Gate

Before a classified task is auto-routed, it passes through `evaluate_task_routing_gate(category, confidence, text)`. There is no combined 0-100 score; it's a single classifier-confidence float compared against two configured thresholds (`task_routing_auto_threshold = 0.90`, `task_routing_floor = 0.70`), plus two hard overrides that bypass the threshold check entirely:

1. **Urgent keyword match** (reuses `triage_service`'s `URGENT_KEYWORDS`) — always routes to human review, regardless of category or confidence. This check runs first, ahead of everything else, so an urgent message from an unrecognised or ambiguous sender is never buried behind other processing.
2. **`COMPLAINT_ESCALATION` category** — always routes to human review, regardless of confidence.

If neither override fires:

- `confidence >= 0.90` → **auto-routed**, proceeds on the assigned path.
- `0.70 <= confidence < 0.90` → **auto-routed, flagged** for audit sampling — the task still proceeds, but is marked for review.
- `confidence < 0.70` → **human review** — held for a person before any action.

## Core Principles

- Route by classified category and confidence, not keyword matching alone (except the urgent-keyword override, which is a deliberate safety bypass, not the primary routing mechanism).
- Clinical requests are never handled by a non-clinical role. `PRESCRIPTION_RENEWAL` and `RESULTS_ENQUIRY` always route to `DOCTOR`; the system never generates clinical content itself.
- AI-suggested actions (for example, suggested appointment slots) are advisory. A human confirms before anything commits.
- Default deny. Low confidence escalates to human review rather than guessing.

## Why This Structure

- Correct handling of patient requests by the role that holds authority.
- A single, calibrated confidence gate that every category passes through the same way, with two named, auditable overrides rather than an unexplained combined score.
- A default-deny fallback so low-confidence classification is never guessed through.