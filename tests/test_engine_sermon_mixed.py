# tests/test_engine_sermon_mixed.py
import os
import pytest

from app.transcription.engine import transcribe_audio, TranscriptionConfig


SERMON_PATHS = [
    "app/storage/Sermon_Audio_1.mp3",
    "app/storage/audio_2_speakers1.mp4",
    "app/storage/audiotest.m4a",
]


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


@pytest.mark.integration
def test_sermon_audio_transcribe_non_empty_and_debug():
    path = _first_existing(SERMON_PATHS)
    if not path:
        pytest.skip("No sermon/mixed audio file found under app/storage/")

    cfg = TranscriptionConfig(model_size="small")
    text, dbg = transcribe_audio(path, cfg=cfg, debug=True)

    assert isinstance(text, str)
    assert len(text.strip()) > 20

    assert "speaker_ht_density" in dbg
    assert 0.0 <= float(dbg["speaker_ht_density"]) <= 1.0

    assert "speaker_mode" in dbg
    assert dbg["speaker_mode"] in ("none", "restricted", "full_possible")
