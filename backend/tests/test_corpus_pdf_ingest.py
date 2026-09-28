"""Checks for scripts/ingest_corpus_documents.py.

No database, no embeddings: the two things that actually break this batch job
are a PDF whose text layer doesn't extract back, and a corpus doc_type the
ClinicalDocType enum doesn't have (the job is halfway through 100 patients
before it finds out).
"""

from __future__ import annotations

from app.models.clinical_document import ClinicalDocType
from app.rag.doc_scopes import DOC_TYPE_TO_SCOPE
from app.rag.text_extraction import extract_pdf_text
from scripts.ingest_corpus_documents import CORPUS_DIR, manifest_documents, render_pdf

SAMPLE = """Consultation Note

Patient: Alicia Roth
DOB: 2001-02-09

Vitals: BP 133/83 mmHg, Weight 84.8 kg
Plan: Review in 6 months
"""


def test_rendered_pdf_extracts_back_to_its_source_text() -> None:
    extracted = extract_pdf_text(render_pdf(SAMPLE))
    for line in (line.strip() for line in SAMPLE.splitlines()):
        if line:
            assert line in extracted


def test_long_document_survives_the_page_break() -> None:
    body = "\n".join(f"Result line {i}: haemoglobin 141 g/L" for i in range(200))
    extracted = extract_pdf_text(render_pdf(body))
    assert "Result line 0:" in extracted
    assert "Result line 199:" in extracted


def test_every_corpus_doc_type_is_a_known_document_type_and_scope() -> None:
    doc_types = {
        doc_type
        for patient_dir in sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir())
        for _path, doc_type in manifest_documents(patient_dir)
    }
    assert doc_types, "corpus has no manifest documents"
    for doc_type in doc_types:
        ClinicalDocType(doc_type)  # raises ValueError on an unmapped corpus type
        assert doc_type in DOC_TYPE_TO_SCOPE


def test_org_profile_ingest_script_imports():
    # It imported DOC_TYPE_TO_SCOPE from scripts.ingest_corpus after the
    # mapping moved to app.rag.doc_scopes, so a fresh environment could not
    # load the org corpus at all and every draft went ungrounded.
    import scripts.ingest_org_profile  # noqa: F401


def test_org_profile_chunks_keep_table_rows_whole_under_their_heading():
    # Fixed 500-char slices of whitespace-collapsed text ended one chunk on
    # "Saturday |" and began the next on "9:00 AM to 2:00 PM", so retrieval
    # served a time with no day and the agent auto-sent "opens at 8:30 AM".
    from scripts.ingest_org_profile import _chunk

    rows = "\n".join(f"| Day{i} | {i}:00 AM to 2:00 PM |" for i in range(40))
    text = f"<!-- doc_type: x | access_scope: general -->\n# Clinic\n## Opening Hours\n| Day | Hours |\n|---|---|\n{rows}\n## Parking\nPaid parking nearby."
    chunks = _chunk(text, 200)

    assert len(chunks) > 1
    for i in range(40):
        holding = [c for c in chunks if f"| Day{i} | {i}:00 AM to 2:00 PM |" in c]
        assert len(holding) == 1 and holding[0].startswith("Opening Hours")
    assert any(c.startswith("Parking") and "Paid parking" in c for c in chunks)
    assert not any("doc_type" in c or "|---|" in c for c in chunks)
