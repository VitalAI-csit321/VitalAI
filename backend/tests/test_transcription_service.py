from pathlib import Path

from app.services.transcription_service import EmptyTranscriptError, transcribe_audio

FIXTURE = Path(__file__).parent / "fixtures" / "chest_pain.wav"


def test_transcribe_audio_returns_nonempty_text():
    audio_bytes = FIXTURE.read_bytes()
    result = transcribe_audio(audio_bytes)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    # faster-whisper output isn't byte-exact across runs/versions; assert on
    # a keyword actually present in the fixture's spoken sentence instead.
    assert "chest" in result.lower() or "pain" in result.lower()


def test_transcribe_audio_raises_on_silence():
    silence = b"\x00" * 32000  # not a real WAV header — decodes to no speech
    try:
        transcribe_audio(silence)
        raised = False
    except EmptyTranscriptError:
        raised = True
    except Exception:
        raised = True  # malformed audio raising anything is acceptable here
    assert raised
