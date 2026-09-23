# Intent classifier: embeddings + logistic regression vs the LLM classifier

Offline measurement, 2026-09-23, with a real-email follow-up on 2026-09-24. Nothing here is
wired into the application.

> **Read this first: the real emails reverse the accuracy result.** On 450 synthetic emails
> the regression beat the LLM (89.6% vs 78.5%). On the 53 in-scope real emails in
> `vitalai_qa`, the **LLM wins clearly: 96.2% vs 75.5%.** The regression failed on phrasings
> its synthetic training data never contained. The confidence finding **does** hold on real
> mail, and more strongly. The LLM said 0.90 or 0.95 on every email, including gibberish and a
> Microsoft newsletter. The regression's margin separated its right answers from its wrong
> ones (AUROC 0.96; all 13 errors had margins of 0.036 or less). See [Real emails](#real-emails-2026-09-24). The synthetic sections below are kept
> as they were written.

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

## Real emails (2026-09-24)

### What was done, in order

1. Read all 58 emails in `vitalai_qa` (14 from the Outlook mailbox, 44 from the API) in a
   read-only session, and labelled each one with no model output in view.
2. **Committed the labels on their own (`7a8c740`) before either classifier ran**, together
   with the analysis plan, including the threshold rule. The git history shows the order.
3. Ran `evaluate_real.py` once. It uses the saved `model.joblib` with no retraining, and the
   production LLM prompt and parser. Both classifiers get the text production builds:
   `Subject: ...` followed by the body (`email_service.py`).

`real_labels.jsonl` stores email ids, labels, a certainty flag and a short note, **but not the
email text**, because the text contains a real personal address. The script reads the text
from `vitalai_qa` at run time. Anyone re-running it needs that database.

**Who labelled:** Claude, the AI assistant running this session, not a person. The brief asked
for a human. These labels need a human check, and one specific risk goes with that: an AI
labeller may share the LLM classifier's instincts, which would favour the LLM in this
comparison.

### The set

| | Count |
|---|---|
| All emails | 58 |
| Out of scope (2 UI delete tests, a Microsoft terms-of-use notice, gibberish, "I have a question" with nothing else) | 5 |
| In scope | 53 |
| In scope, duplicate bodies removed | 37 |
| In scope and labelled "clear" rather than "borderline" | 36 |

In-scope labels: appointment_request 19, general_administrative 17, prescription_renewal 11,
urgent_emergency 2, and 1 each of complaint, onboarding, records and billing.
**results_enquiry and referral_request do not appear at all.** Most of these emails are
developer test messages, many repeated with small edits. This is a small, lopsided set, not a
benchmark.

### Accuracy

| Subset | n | Regression | LLM |
|---|---|---|---|
| All in-scope | 53 | **75.5%** | **96.2%** |
| Deduplicated | 37 | 78.4% | 97.3% |
| Clear labels only | 36 | 94.4% | 100% |
| (diagnostic) regression on body only, no subject line, all in-scope | 53 | 73.6% | n/a |

Per-category recall on all in-scope emails:

| Category (n) | Regression | LLM |
|---|---|---|
| appointment_request (19) | **0.53** | 1.00 |
| general_administrative (17) | 0.76 | 0.88 |
| prescription_renewal (11) | 1.00 | 1.00 |
| urgent_emergency (2) | 1.00 | 1.00 |
| complaint, onboarding, records, billing (1 each) | 1.00 each | 1.00 each |

Confusion matrices, all 53 in-scope (rows = true label, columns = predicted; order appt,
onboard, rx, results, referral, records, billing, complaint, general, urgent). Rows for
results and referral are all zeros and are omitted.

```
Regression                      LLM
appt      10 1 0 4 3 0 0 0 0 1    19 0 0 0 0 0 0 0 0 0
onboard    0 1 0 0 0 0 0 0 0 0     0 1 0 0 0 0 0 0 0 0
rx         0 0 11 0 0 0 0 0 0 0    0 0 11 0 0 0 0 0 0 0
records    0 0 0 0 0 1 0 0 0 0     0 0 0 0 0 1 0 0 0 0
billing    0 0 0 0 0 0 1 0 0 0     0 0 0 0 0 0 1 0 0 0
complaint  0 0 0 0 0 0 0 1 0 0     0 0 0 0 0 0 0 1 0 0
general    0 0 0 0 4 0 0 0 13 0    2 0 0 0 0 0 0 0 15 0
urgent     0 0 0 0 0 0 0 0 0 2     0 0 0 0 0 0 0 0 0 2
```

**Why the regression failed:** 11 of its 13 errors are one kind of email: "Is there any GP I
can consult with?" and "Is there any GP I can see this week?", sent many times as tests. It
called these referral_request or results_enquiry. Nothing like that phrasing was in the
synthetic scenarios. The other two errors: "I wanna see a GP, can I get an appointment?"
became referral_request, and the Dutch email about an appointment became urgent_emergency.
A classifier trained on 315 synthetic emails knows only the phrasings in those emails. That
is the "synthetic data reads optimistically" caveat below, now measured: an 11-point lead on
synthetic data became a 21-point deficit on real mail.

**The LLM's two errors** were both "Is there any GP I can consult with? can I get the list of
GPs" emails, which I labelled general_administrative *and* marked borderline. The LLM called
them appointment_request. Reasonable people would disagree on those two.

### Confidence on real mail

| | Regression margin | LLM self-reported |
|---|---|---|
| Values seen, all 53 in-scope | 42 distinct | **2 (0.90 on 48, 0.95 on 5)** |
| Mean when right / wrong | top-1 0.222 / 0.142 | 0.905 / 0.900 |
| AUROC, right vs wrong (0.5 = coin toss) | **0.96** (top-1: 0.975) | **0.55** |
| Largest margin on any of its own errors | 0.036 | n/a |

**Out-of-scope emails** are the plainest test of whether a confidence number means anything:

| Email | Regression prediction, margin | LLM prediction, confidence, gate |
|---|---|---|
| "Live delete test" | results_enquiry, 0.034 | general_administrative, 0.90, auto-routed |
| "BROWSER DELETE TEST" | results_enquiry, 0.009 | general_administrative, 0.90, auto-routed |
| Microsoft terms-of-use notice | billing_insurance_enquiry, 0.024 | general_administrative, 0.90, auto-routed |
| "Hello ... I have a question" | urgent_emergency, 0.005 | general_administrative, 0.90, auto-routed |
| "xkcd qqq" gibberish | urgent_emergency, 0.007 | general_administrative, 0.90, auto-routed |

The LLM's *category* for these is the harmless fallback, which is good. But it was 0.90 sure
of gibberish, and all five auto-routed. The regression's categories for these are nonsense,
but every margin is tiny, which is exactly the "I don't know" signal the gate needs.

### The threshold, fixed in advance

Rule from `7a8c740`: split the 37 deduplicated emails with seed 0 into 18 calibration and 19
held-out. Pick the smallest regression margin whose auto-routed accuracy on the calibration
half is at least 95%. Apply it unchanged to the held-out half.

- Threshold chosen: **margin ≥ 0.0335**
- Held-out: **12 of 19 auto-routed, all 12 correct. 7 sent to a human.**
- Out-of-scope emails under the same threshold: 4 of 5 go to a human. "Live delete test"
  (margin 0.0337) clears it by 0.0002.

That is 19 emails, so read it as "the mechanism works as designed", not as an error rate. A
100% on 12 emails fits a real error rate anywhere up to about 25%.

### The urgent keyword net, measured on the synthetic set

`URGENT_KEYWORDS` (7 phrases) matched **16 of the 45** synthetic emergency emails, and **28**
emails in *other* categories: anxious or angry non-emergencies that say "urgent" or
"immediately". Those false alarms go to a human, which is the safe direction and only costs
staff time. Missing 29 of 45 emergencies is the real problem (spec F.97).

### What the real emails change

- **Do not replace the LLM's category with the regression's.** On real mail the LLM is
  clearly more accurate. The synthetic result that suggested otherwise came from a training
  set that missed whole kinds of real phrasing.
- **The case for a computed confidence is stronger than before.** The LLM's number was 0.90
  or 0.95 on everything, gibberish included. The regression's margin separated right from
  wrong well on real mail (AUROC 0.96) and gave all five out-of-scope emails margins of 0.034
  or less. It is not perfect: across all 53 in-scope emails, one regression error (margin
  0.0363) would still clear the 0.0335 threshold.
- **The open question** is whether a *regression* margin says anything about when the *LLM* is
  wrong, since you would keep the LLM's category. The LLM made only 2 errors here, so this
  set cannot answer it. Its two errors had regression margins of 0.0308 and 0.0363. Against
  the 0.0335 threshold, one would go to a human and one would still auto-route. Two data
  points are an anecdote, not evidence.
- **Retraining the regression with real phrasings would help, but not on these 58 emails.**
  They are the only real test set there is. Train on them and nothing is left to measure with.

## Honest read (written 2026-09-23, before the real-email run)

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

## Next steps

Done on 2026-09-24: the real-email measurement above. Still open:

1. **A person checks `real_labels.jsonl`**, especially the 17 marked borderline. If labels
   change, re-run `evaluate_real.py` and report both versions.
2. **Collect more real mail**, especially the categories with zero or one example (results,
   referral, complaint, billing, records, onboarding). Until then, per-category claims on real
   mail are not possible.
3. **Test the hybrid**: keep the LLM's category and route on the regression margin. This needs
   enough real LLM errors to measure whether a low margin predicts them.
4. **Widen `URGENT_KEYWORDS`** (F.97). That is an `app/` change and was not made here.

## Files

| File | What |
|---|---|
| `generate.py` | Dataset generator, resumable |
| `dataset.jsonl` | The 450 labelled emails, `{"text", "label", "notes"}` |
| `evaluate.py` | Embed, split, fit once, measure both systems |
| `model.joblib` | The fitted regression plus metadata. It expects nomic `search_document:`-prefixed 512-dim vectors, which is what `embed_documents` produces |
| `results.json` | Every number above, including the full classification reports |
| `test_predictions.jsonl` | Per test email: label, both predictions, top-1, margin, LLM confidence, LLM raw reply |
| `real_labels.jsonl` | Labels for the 58 `vitalai_qa` emails, by id, committed before any prediction |
| `evaluate_real.py` | Real-email measurement (reads `vitalai_qa` read-only, no retraining) |
| `real_results.json` | Every real-email number above |
| `real_predictions.jsonl` | Per real email, by id: label, both predictions, margin, LLM confidence, gate outcome, keyword hit (no email text) |

The AUROC, McNemar and gate-replay figures were computed afterwards from
`test_predictions.jsonl`, with no refit. Recompute them with `sklearn.metrics.roc_auc_score`
(is-correct vs score), `scipy.stats.binomtest(9, 33)`, and `evaluate_task_routing_gate`
applied to each row.
