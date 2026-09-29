"""Local speech-to-text for call logging (faster-whisper, CPU, Phase 1 MVP).

Lazy-loaded module-level singleton — same pattern as
NomicEmbedProvider._get_model() in app/rag/embeddings.py. No live telephony
here; audio comes from a file upload (see app/routes/calls.py).
"""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

_model: WhisperModel | None = None

# vad_filter: without it large-v3-turbo transcribes silence and hiss as
# "Thank you." with no_speech_prob near 0, so a silent voicemail passed the
# quality gate. initial_prompt: clinic vocabulary; on a real call it turned
# "any peace laws" / "any fees lost" into "any free slots". language is left
# to detection on purpose: forcing it pins language_probability to 1.0 and
# disables that quality check.
_TRANSCRIBE_OPTIONS = {
    "vad_filter": True,
    "initial_prompt": (
        "Clinic voicemail. Appointment, booking, free slots, openings, availability, fees, "
        "bulk billing, Medicare, test results, prescription, referral, date of birth, "
        "phone number."
    ),
}


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
    segments, _ = model.transcribe(io.BytesIO(audio_bytes), **_TRANSCRIBE_OPTIONS)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise EmptyTranscriptError("No speech detected in the uploaded audio")
    return text


@dataclass(frozen=True)
class TranscriptQuality:
    avg_logprob: float | None
    no_speech_prob: float | None
    language_probability: float | None
    low: bool

    @classmethod
    def empty(cls) -> TranscriptQuality:
        return cls(None, None, None, low=True)

    def as_dict(self) -> dict:
        return asdict(self)


def transcribe_audio_with_quality(audio_bytes: bytes) -> tuple[str, TranscriptQuality]:
    """For voicemail: the transcript plus how far to trust it. Silence is an
    empty, low-quality transcript, never an error: a silent voicemail still
    has a caller ID worth calling back."""
    model = _get_model()
    segments_iter, info = model.transcribe(io.BytesIO(audio_bytes), **_TRANSCRIBE_OPTIONS)
    segments = list(segments_iter)  # a generator; transcription happens here
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not segments:
        return "", TranscriptQuality(None, None, info.language_probability, low=True)
    avg_logprob = sum(s.avg_logprob for s in segments) / len(segments)
    no_speech = max(s.no_speech_prob for s in segments)
    language = info.language_probability
    low = (
        not text
        or avg_logprob < settings.voicemail_min_avg_logprob
        or no_speech > settings.voicemail_max_no_speech_prob
        or language < settings.voicemail_min_language_probability
    )
    return text, TranscriptQuality(
        round(avg_logprob, 4), round(no_speech, 4), round(language, 4), low=low
    )
