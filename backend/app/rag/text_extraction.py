"""Plain-Python PDF text extraction for the clinical upload path (RBAC report section 8).

Mirrors ingestion/matthew_corpus/ingestion/Loader.py's PDF branch (page join)
and Cleaner.py's whitespace normalization, as plain functions instead of Ray
remote tasks: this runs once per HTTP upload, not across a 100-patient batch
job, so there is no distributed-compute workload to offload to Ray here.
"""

from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader

_WHITESPACE_RE = re.compile(r"\s+")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract and clean the text layer from a PDF's pages.

    Returns an empty string for an image-only PDF (no text operators on any
    page) - callers must treat that as "no text," not attempt to ingest it.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    cleaned = _WHITESPACE_RE.sub(" ", raw_text.replace("\n", " "))
    return cleaned.strip()
