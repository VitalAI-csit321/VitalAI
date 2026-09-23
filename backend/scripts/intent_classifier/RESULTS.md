# Intent classifier: embeddings + logistic regression vs the LLM classifier

Offline measurement, 2026-09-23. Nothing here is wired into the application.

## Why this exists

The production classifier (`app/services/content_classifier.py`) asks the LLM to report its
own confidence as part of its JSON reply. Nothing computes that number; the model types it.
Auto-routing trusts it (`>= 0.90` auto-routes). This experiment checks two things: does that
number mean anything, and can a classifier whose confidence is actually *computed*, from
local sentence embeddings, do the same job. Local embeddings do not depend on which LLM
provider is used, so this approach survives the Bedrock migration (spec G.23).

## What was generated

- 450 synthetic emails, **45 per category**, all 10 `TaskCategory` values. All 450 are unique.
- Generator: `generate.py`, local Ollama `gemma2:2b`, temperature 0.9, a fixed seed per email.
- **The label was chosen first.** The model was told "write an email where the sender wants
  to X" and the label is X. No model ever labelled existing text.
- Deliberate variation, drawn at random per email (counts across all 450):

| Axis | Values (count) |
|---|---|
| Length | one short line (101), 2-3 sentences (132), one paragraph (96), several paragraphs (121) |
| Register | casual (98), polite/formal (91), anxious (90), angry (89), blunt (82) |
| Sender | the patient, a parent about a child, an adult child about an elderly parent |
| Signed | named (286), anonymous (164) |
| Typos | 124 had typo noise added after generation: lowercased, most punctuation removed, letters swapped in about 6% of words |
| Multi-intent | 69 mention a second, minor matter. The label is the main intent; the record's `notes` names both. An emergency is never the minor matter, because an email that reports an emergency is urgent whatever else it says. |

- 7 or 8 scenarios per category (for example, prescription_renewal includes "running out of
  blood pressure medication" and "pharmacy says no repeats left"). All of them are in
  `generate.py`.
- gemma2:2b wrote placeholders such as `[Parent's name]` into 232 of the 450 emails even
  though the prompt told it not to. Throwing those emails away would have removed most of the
  long, formal ones, so the placeholders were filled with realistic values (a name, a date, a
  doctor). That sometimes reads oddly, for example "reschedule my appointment for two weeks
  ago". The number filled is recorded in each email's `notes`.
- Median length is 246 characters (range 36 to 1790).

### Label noise (measured, not assumed)

"Label first" means the label is what was *asked for*. A 2B model does not always write what
it was asked for. A random sample of 40 emails was read against its label:

- **4 of 40 (10%) are clearly wrong.** Two labelled onboarding and records read as
  complaints, one "referral" email makes no request at all, and one multi-intent email made the
  *minor* matter (a double charge) the main one.
- **3 more are borderline**: two "send me a copy of my pathology results" emails sit between
  results_enquiry and medical_records_request, and one results enquiry is mostly a complaint.

The labels were **not** corrected. Correcting them after reading the text would throw away
the one guarantee this dataset has. The sample was reviewed by Claude, the AI assistant
running this session, not by a person. Treat about 10% as a rough ceiling on how wrong the
labels are, not as a validated figure. Neither classifier can be expected to score much
above about 90% against these labels.

## Method

- Embeddings: the project's own `get_embedding_provider()` (nomic-embed-text-v1 via
  sentence-transformers, local, in-process), in one batched `embed_documents` call.
  **450 vectors, 512 dimensions**, 22.3 s including the model load.
- Split: stratified, 70/30, `random_state=42`. **315 train / 135 test**, 13 or 14 of each
  category in the test half.
- Regression: `LogisticRegression(max_iter=5000)`, all other settings default. **Fitted
  once**, on one split, never re-fitted after seeing the test numbers.
- LLM: the production `get_llm()` (gemma2:2b, temperature 0.3), given the exact production
  prompt (`_PROMPT_TEMPLATE` with the email channel framing) and parsed by the production
  parser `_parse_classification`. The injection guardrail was not run. On a parse failure the
  script would have applied the same fallback as `classify_content()`, general_administrative
  at 0.0; there were none.
- Re-run: `generate.py`, then `evaluate.py`. `evaluate.py` writes `results.json` with every
  number and `test_predictions.jsonl` with every test email's predictions, plus the LLM's raw
  replies. Running it again makes new LLM calls, so the LLM figures can move slightly.

## Results

### Headline

| | Regression (embeddings) | LLM (gemma2:2b) |
|---|---|---|
| Accuracy, 135 test emails | **89.6%** (121/135) | **78.5%** (106/135) |
| Macro precision / recall | 0.913 / 0.899 | 0.817 / 0.787 |
| Parse failures | n/a | 0 (108 of 135 replies wrapped in a ```json fence; all parsed) |

Paired comparison on the same 135 emails: only the regression was wrong on 9, only the LLM
on 24, both on 5. Exact McNemar test, **p = 0.014**. On *this* data the gap is unlikely to be
chance. With 135 emails the uncertainty on each accuracy is roughly ±5 to ±7 points.

### Per-category recall (precision in brackets), test support 13-14 each

| Category | Regression | LLM |
|---|---|---|
| appointment_request | 1.00 (0.93) | 0.85 (0.58) |
| new_patient_onboarding | 1.00 (0.87) | 0.77 (0.83) |
| prescription_renewal | 1.00 (0.74) | 0.86 (0.75) |
| results_enquiry | 1.00 (0.93) | 0.85 (1.00) |
| referral_request | 0.85 (0.92) | 0.85 (1.00) |
| medical_records_request | 1.00 (0.82) | 0.79 (0.85) |
| billing_insurance_enquiry | 1.00 (0.93) | 0.92 (1.00) |
| **complaint_escalation** | **0.50** (1.00) | **0.64** (0.56) |
| general_administrative | 0.71 (1.00) | 0.64 (0.60) |
| **urgent_emergency** | **0.93** (1.00) | **0.71** (1.00) |

Every category is predicted by both systems; none goes missing. **The LLM is better on
complaints.** The regression misses half of them. In every missed case the complaint was
*about* a topic that has its own category: a prescription error went to prescription_renewal
(3 times), a privacy breach and unreturned calls to medical_records_request, a long wait to
appointment_request. The embedding captures the topic; it does not capture that the sender
is complaining.

### Confusion matrices (rows = true label, columns = predicted, same order as the rows)

Column order: appt, onboard, rx, results, referral, records, billing, complaint, general, urgent.

Regression:
```
appointment_request     13  0  0  0  0  0  0  0  0  0
new_patient_onboarding   0 13  0  0  0  0  0  0  0  0
prescription_renewal     0  0 14  0  0  0  0  0  0  0
results_enquiry          0  0  0 13  0  0  0  0  0  0
referral_request         0  0  0  1 11  1  0  0  0  0
medical_records_request  0  0  0  0  0 14  0  0  0  0
billing_insurance        0  0  0  0  0  0 13  0  0  0
complaint_escalation     1  0  3  0  0  2  1  7  0  0
general_administrative   0  2  1  0  1  0  0  0 10  0
urgent_emergency         0  0  1  0  0  0  0  0  0 13
```

LLM:
```
appointment_request     11  0  0  0  0  0  0  0  2  0
new_patient_onboarding   0 10  0  0  0  0  0  1  2  0
prescription_renewal     1  0 12  0  0  0  0  1  0  0
results_enquiry          0  0  1 11  0  0  0  1  0  0
referral_request         1  0  0  0 11  1  0  0  0  0
medical_records_request  0  1  0  0  0 11  0  2  0  0
billing_insurance        0  0  0  0  0  0 12  1  0  0
complaint_escalation     1  0  1  0  0  1  0  9  2  0
general_administrative   3  1  1  0  0  0  0  0  9  0
urgent_emergency         2  0  1  0  0  0  0  1  0 10
```

### Confidence: the point of the exercise

| | Regression top-1 probability | Regression margin (top-1 minus top-2) | LLM self-reported confidence |
|---|---|---|---|
| Distinct values over 135 emails | 132 | 132 | **3** |
| Min / median / max | 0.137 / 0.228 / 0.401 | 0.002 / 0.100 / 0.312 | 0.80 / 0.90 / 0.95 |
| Standard deviation | 0.054 | 0.068 | 0.018 |
| Most common value | (none repeats more than twice) | | **0.90 on 120 of 135** |
| Mean when right / when wrong | 0.238 / 0.195 | 0.116 / 0.052 | 0.906 / 0.898 |
| **AUROC: does it rank right answers above wrong ones?** (0.5 = coin toss) | 0.74 | **0.80** | **0.56** |

What this shows:

1. **The expected result holds.** The LLM's confidence is almost constant: 0.9 on 120 of 135
   emails, and 0.9 on right and wrong answers alike (0.906 vs 0.898). Its AUROC of 0.56 is
   close to a coin toss. It carries almost no information about whether the classification
   is right.
2. **The regression's numbers vary and they do carry information.** The margin is the
   better signal (AUROC 0.80 against 0.74 for top-1). A wrong answer has on average less than
   half the margin of a right one.
3. **But the regression's probabilities are small, and that matters in practice.** The
   highest top-1 on any test email was 0.40. Default logistic regression shrinks its weights
   (regularisation, C=1.0). With 315 training emails spread over 512 dimensions and 10
   classes, that spreads the probability out. **Put straight behind today's gate, the
   regression would send all 135 emails to human review**, because none reaches the 0.70 floor.
   The 0.90 and 0.70 thresholds were written with the LLM's number in mind and do not carry
   over. A threshold for this model has to be chosen on a separate, labelled calibration set,
   not on this test set. That is not done here, on purpose.

### What today's gate actually does with the LLM's number

The LLM's predictions were replayed through the real `evaluate_task_routing_gate` (called
unchanged, no database):

- 106 auto-routed, 1 auto-routed-and-flagged, 28 sent to human review. All 28 went to review
  because of the complaint, urgent-category or urgent-keyword rules. **Confidence sent none of
  them there.**
- **22 wrong classifications were auto-routed.**
- **3 of those were true emergencies.** "My elderly parent has fallen and can't get up for
  hours" was classified appointment_request at 0.90, and two overdose emails went to
  appointment_request (0.95) and prescription_renewal (0.80, auto-routed-flagged). The
  urgent-keyword net caught none of the three. Only one of the regression's 135 test emails
  was a missed emergency (the same overdose email, sent to prescription_renewal).

## Honest read

- **These are synthetic emails, and synthetic emails are easier than real ones.** Read the
  accuracies as optimistic, especially the regression's. Four reasons:
  - The same 7 or 8 scenarios per category appear in both the training and the test half, so
    the regression is partly recognising scenarios it has already seen. The LLM saw no
    training data at all. The comparison is therefore tilted toward the regression.
  - Real mail looks different. The 58 emails in `vitalai_qa` (read-only) have a median
    length of 96 characters, against 246 here. They include quoted reply chains, at least one
    email in Dutch, and exact duplicates, and this set has none of those.
  - About 10% of the labels are estimated to be wrong (see above).
  - This is one split, 135 test emails, and one seed.
- **The central claim does not depend on those caveats.** The LLM's self-reported confidence
  is a near-constant that does not track correctness. That holds on the easiest data this
  project will ever see, so it will not improve on harder data.
- **The regression is not a drop-in replacement.** Its complaint recall (0.50) is worse than
  the LLM's (0.64), and complaints are a category the gate forces to human review. Its
  probabilities need calibrating before any threshold means anything.
- A reasonable next design, **not built here**: use the regression's *margin* as the
  computed confidence signal and route low-margin emails to a human. Either keep the LLM's
  category or use the regression's, but choose on real data. Keep the complaint and urgent
  keyword rules, since both classifiers miss some of both.

## Recommended next step (not in scope, not done)

Hand-label a real test set. There are 58 emails in the `vitalai_qa` database. The task brief
says 13 of them came from the real mailbox; this session did not verify that count. Label
them **by hand, by a person, without looking at any model's prediction**. Do **not** reuse the
65 existing task labels, because they came from the classifier being evaluated. Then:

1. Run both classifiers on them, with no retraining.
2. Choose a margin threshold on part of the labelled data and report on the rest.
3. Pay particular attention to complaint and urgent recall.

58 emails is small. Treat the result as a sanity check, not a benchmark.

## Files

| File | What |
|---|---|
| `generate.py` | Dataset generator, resumable |
| `dataset.jsonl` | The 450 labelled emails, `{"text", "label", "notes"}` |
| `evaluate.py` | Embed, split, fit once, measure both systems |
| `model.joblib` | The fitted regression plus metadata. It expects nomic `search_document:`-prefixed 512-dim vectors, which is what `embed_documents` produces |
| `results.json` | Every number above, including the full classification reports |
| `test_predictions.jsonl` | Per test email: label, both predictions, top-1, margin, LLM confidence, LLM raw reply |

The AUROC, McNemar and gate-replay figures were computed afterwards from
`test_predictions.jsonl`, with no refit. Recompute them with `sklearn.metrics.roc_auc_score`
(is-correct vs score), `scipy.stats.binomtest(9, 33)`, and `evaluate_task_routing_gate`
applied to each row.
