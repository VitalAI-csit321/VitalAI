"""Plain-Python character-based chunking for the clinical upload path.

Same shape as ingestion/matthew_corpus/ingestion/Chunker.py's chunk_text, as
a plain function instead of a Ray remote task - this runs once per HTTP
upload, not across a 100-patient batch job. scripts/ingest_corpus.py and the
Ray-based Chunker are untouched; this is a separate implementation for the
separate (HTTP-request-scoped) ingestion path.
"""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
