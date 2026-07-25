"""Manifest for the FR-RAG-01 synthetic fixture corpus.

SYNTHETIC DATA ONLY. Every patient, document, and content string here is
fabricated for exercising vector retrieval end to end — none of it is real
patient data. Ids are fixed (not random) so tests can query "as" a specific
synthetic patient and assert on exact chunk counts.

BASELINE, reconcile with Matthew's ingestion schema: doc_type and
access_scope values below are placeholder vocabulary, not a ratified list.
Two entries (ALICE_MENTAL_HEALTH, ALICE_BILLING) are deliberately named so
that doc_type and access_scope disagree with what the name would suggest —
this exists to prove the security filter keys on access_scope, never on
doc_type. See docs/FR-RAG-01_handoff.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

CORPUS_DIR = Path(__file__).parent

PATIENT_ALICE = UUID("11111111-1111-1111-1111-111111111111")
PATIENT_BOB = UUID("22222222-2222-2222-2222-222222222222")
PATIENT_CAROL = UUID("33333333-3333-3333-3333-333333333333")
PATIENT_DAVE = UUID("44444444-4444-4444-4444-444444444444")

# Named so tests can reference specific documents without re-deriving ids.
ALICE_CHECKUP_DOC = UUID("a1000000-0000-0000-0000-000000000001")
ALICE_LAB_PANEL_DOC = UUID("a1000000-0000-0000-0000-000000000002")
ALICE_REFERRAL_DOC = UUID("a1000000-0000-0000-0000-000000000003")
ALICE_MENTAL_HEALTH_DOC = UUID("a1000000-0000-0000-0000-000000000004")
ALICE_BILLING_DOC = UUID("a1000000-0000-0000-0000-000000000005")
BOB_CHECKUP_DOC = UUID("b2000000-0000-0000-0000-000000000001")
BOB_LAB_PANEL_DOC = UUID("b2000000-0000-0000-0000-000000000002")
CAROL_REFERRAL_DOC = UUID("c3000000-0000-0000-0000-000000000001")
CAROL_BILLING_DOC = UUID("c3000000-0000-0000-0000-000000000002")
DAVE_MEDS_DOC = UUID("d4000000-0000-0000-0000-000000000001")


@dataclass(frozen=True)
class SyntheticDoc:
    source_document_id: UUID
    patient_id: UUID
    doc_type: str
    access_scope: str
    filename: str  # relative to CORPUS_DIR, blank-line-separated paragraphs = chunks

    def read_chunks(self) -> list[str]:
        raw = (CORPUS_DIR / self.filename).read_text(encoding="utf-8")
        return [p.strip() for p in raw.split("\n\n") if p.strip()]


DOCS: list[SyntheticDoc] = [
    SyntheticDoc(
        ALICE_CHECKUP_DOC, PATIENT_ALICE, "clinical_note", "general", "alice_checkup.txt"
    ),
    SyntheticDoc(
        ALICE_LAB_PANEL_DOC, PATIENT_ALICE, "lab_result", "restricted", "alice_lab_panel.txt"
    ),
    SyntheticDoc(
        ALICE_REFERRAL_DOC, PATIENT_ALICE, "referral_letter", "general", "alice_referral.txt"
    ),
    # Divergence case: an ordinary-sounding doc_type locked to a sensitive scope.
    SyntheticDoc(
        ALICE_MENTAL_HEALTH_DOC,
        PATIENT_ALICE,
        "clinical_note",
        "sensitive",
        "alice_mental_health.txt",
    ),
    # Divergence case: an alarming-sounding doc_type that is actually general access.
    SyntheticDoc(
        ALICE_BILLING_DOC, PATIENT_ALICE, "sensitive_summary", "general", "alice_billing.txt"
    ),
    SyntheticDoc(BOB_CHECKUP_DOC, PATIENT_BOB, "clinical_note", "general", "bob_checkup.txt"),
    SyntheticDoc(
        BOB_LAB_PANEL_DOC, PATIENT_BOB, "lab_result", "restricted", "bob_lab_panel.txt"
    ),
    SyntheticDoc(
        CAROL_REFERRAL_DOC, PATIENT_CAROL, "referral_letter", "general", "carol_referral.txt"
    ),
    SyntheticDoc(
        CAROL_BILLING_DOC, PATIENT_CAROL, "billing_record", "sensitive", "carol_billing.txt"
    ),
    # Dave is deliberately small: exactly one doc, two chunks — used to check
    # that a narrow patient filter isn't accidentally over-filtered down
    # further inside a larger corpus.
    SyntheticDoc(DAVE_MEDS_DOC, PATIENT_DAVE, "clinical_note", "general", "dave_meds.txt"),
]
