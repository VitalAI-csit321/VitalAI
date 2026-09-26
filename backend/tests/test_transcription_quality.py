from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import transcription_service
from app.services.transcription_service import transcribe_audio_with_quality


def _model(segments, language_probability=0.98):
    info = SimpleNamespace(language_probability=language_probability)
    return SimpleNamespace(transcribe=lambda audio: (iter(segments), info))


def _seg(text, avg_logprob=-0.3, no_speech_prob=0.02):
    return SimpleNamespace(text=text, avg_logprob=avg_logprob, no_speech_prob=no_speech_prob)


@pytest.fixture(autouse=True)
def thresholds(monkeypatch):
    monkeypatch.setattr(settings, "voicemail_min_avg_logprob", -1.0)
    monkeypatch.setattr(settings, "voicemail_max_no_speech_prob", 0.6)
    monkeypatch.setattr(settings, "voicemail_min_language_probability", 0.5)


def test_clear_speech_is_not_low(monkeypatch):
    monkeypatch.setattr(
        transcription_service, "_get_model", lambda: _model([_seg(" Hi "), _seg("there.")])
    )
    text, quality = transcribe_audio_with_quality(b"audio")
    assert text == "Hi there."
    assert quality.low is False
    assert quality.as_dict()["avg_logprob"] == -0.3


@pytest.mark.parametrize(
    ("segments", "language_probability"),
    [
        ([_seg("mumble", avg_logprob=-1.4)], 0.98),
        ([_seg("hiss", no_speech_prob=0.9)], 0.98),
        ([_seg("words")], 0.3),
    ],
)
def test_each_threshold_marks_low(monkeypatch, segments, language_probability):
    monkeypatch.setattr(
        transcription_service, "_get_model", lambda: _model(segments, language_probability)
    )
    _, quality = transcribe_audio_with_quality(b"audio")
    assert quality.low is True


def test_silence_is_empty_and_low_not_an_error(monkeypatch):
    monkeypatch.setattr(transcription_service, "_get_model", lambda: _model([]))
    text, quality = transcribe_audio_with_quality(b"audio")
    assert text == ""
    assert quality.low is True
