"""Fakes for the voicemail tests. Plain module, no pytest fixtures."""

import json

from app.services import voicemail_service
from app.services.transcription_service import TranscriptQuality


class FakeStorage:
    """Stands in for app.storage.object_storage (MinIO)."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def install(self, monkeypatch) -> "FakeStorage":
        monkeypatch.setattr("app.storage.object_storage.put_object", self._put)
        monkeypatch.setattr("app.storage.object_storage.get_object", self.objects.__getitem__)
        monkeypatch.setattr(
            "app.storage.object_storage.delete_object",
            lambda key: self.objects.pop(key, None),
            raising=False,  # delete_object arrives in the sweep task
        )
        return self

    def _put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data


class FakeClassifier:
    """The model classify_content calls. Records whether it was asked."""

    def __init__(self, category: str = "general_administrative", confidence: float = 0.95):
        self.category = category
        self.confidence = confidence
        self.calls = 0

    async def ainvoke(self, prompt: str) -> str:
        self.calls += 1
        return json.dumps({"category": self.category, "confidence": self.confidence})


def fake_transcript(monkeypatch, text: str, *, low: bool = False) -> None:
    quality = TranscriptQuality(-0.3, 0.02, 0.99, low=low)
    monkeypatch.setattr(
        voicemail_service, "transcribe_audio_with_quality", lambda data: (text, quality)
    )
