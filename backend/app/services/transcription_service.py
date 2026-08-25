"""Local speech-to-text for call logging (faster-whisper, CPU, Phase 1 MVP).

Lazy-loaded module-level singleton — same pattern as
NomicEmbedProvider._get_model() in app/rag/embeddings.py. No live telephony
here; audio comes from a file upload (see app/routes/calls.py).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

_model: WhisperModel | None = None


class EmptyTranscriptError(Exception):
    """Raised when the uploaded audio contains no detectable speech."""


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    return _model


def transcribe_audio(audio_bytes: bytes) -> str:
    model = _get_model()
    segments, _ = model.transcribe(io.BytesIO(audio_bytes))
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise EmptyTranscriptError("No speech detected in the uploaded audio")
    return text
