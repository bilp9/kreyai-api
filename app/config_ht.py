from __future__ import annotations

import os


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


HT_PIPELINE_MODE = os.getenv("HT_PIPELINE_MODE", "thin").strip().lower() or "thin"
HT_MINIMAL_FORMATTING_ONLY = _bool_env("HT_MINIMAL_FORMATTING_ONLY", True)
HT_ENABLE_DIARIZATION_SHORT = _bool_env("HT_ENABLE_DIARIZATION_SHORT", True)
HT_ENABLE_DIARIZATION_LONG = _bool_env("HT_ENABLE_DIARIZATION_LONG", False)
HT_LONG_FORM_MINUTES = _int_env("HT_LONG_FORM_MINUTES", 10)
HT_RESUMABLE_MINUTES = _int_env("HT_RESUMABLE_MINUTES", 45)
HT_MEDIUM_CHUNK_SECONDS = _int_env("HT_MEDIUM_CHUNK_SECONDS", 120)
HT_LONG_CHUNK_SECONDS = _int_env("HT_LONG_CHUNK_SECONDS", 240)
HT_MIN_CHUNK_SECONDS = _int_env("HT_MIN_CHUNK_SECONDS", 90)
HT_MAX_CHUNK_SECONDS = _int_env("HT_MAX_CHUNK_SECONDS", 300)
HT_ENABLE_PROMPT = _bool_env("HT_ENABLE_PROMPT", False)
HT_EXPORT_RAW = _bool_env("HT_EXPORT_RAW", True)
HT_EXPORT_CLEAN = _bool_env("HT_EXPORT_CLEAN", True)
HT_BETA_MULTI_SPEAKER = _bool_env("HT_BETA_MULTI_SPEAKER", True)


def ht_long_form_seconds() -> int:
    return HT_LONG_FORM_MINUTES * 60


def ht_resumable_seconds() -> int:
    return HT_RESUMABLE_MINUTES * 60


def ht_use_thin_pipeline() -> bool:
    return HT_PIPELINE_MODE == "thin"
