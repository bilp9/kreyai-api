from types import SimpleNamespace

from app.transcription import engine
from app.transcription.engine import TranscriptionConfig, normalize_language_code, transcribe_audio


class _FakeModel:
    def __init__(self, detected_language: str = "es"):
        self.detected_language = detected_language
        self.calls = []

    def transcribe(self, audio_path, **kwargs):
        self.calls.append({"audio_path": audio_path, **kwargs})
        segments = [
            SimpleNamespace(
                text=" Hola mundo ",
                start=0.0,
                end=1.0,
                avg_logprob=-0.2,
                words=[],
            )
        ]
        info = SimpleNamespace(language=self.detected_language)
        return iter(segments), info


def test_normalize_language_code_maps_auto_to_none():
    assert normalize_language_code("auto") is None
    assert normalize_language_code(" AUTO ") is None


def test_transcribe_audio_uses_autodetect_for_auto_language(monkeypatch):
    fake_model = _FakeModel(detected_language="es")

    monkeypatch.setattr(engine, "_get_model", lambda cfg: fake_model)
    monkeypatch.setattr(engine, "_load_akademi", lambda: None)

    result = transcribe_audio(
        "fake.wav",
        cfg=TranscriptionConfig(),
        language="auto",
    )

    assert fake_model.calls[0]["language"] is None
    assert result["language_requested"] == "auto"
    assert result["language_detected"] == "es"
    assert result["language"] == "es"
    assert result["text"] == "Hola mundo"


def test_transcribe_audio_preserves_explicit_language(monkeypatch):
    fake_model = _FakeModel(detected_language="fr")

    monkeypatch.setattr(engine, "_get_model", lambda cfg: fake_model)
    monkeypatch.setattr(engine, "_load_akademi", lambda: None)

    result = transcribe_audio(
        "fake.wav",
        cfg=TranscriptionConfig(),
        language="fr",
    )

    assert fake_model.calls[0]["language"] == "fr"
    assert result["language_requested"] == "fr"
    assert result["language_detected"] == "fr"
    assert result["language"] == "fr"


def test_transcription_config_uses_runtime_model_size_env(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "large-v3")

    cfg = TranscriptionConfig()

    assert cfg.model_size == "large-v3"
