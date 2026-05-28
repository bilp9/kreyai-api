import subprocess
import os


def _ht_preprocess_enabled() -> bool:
    raw = os.getenv("KREYAI_HT_ENABLE_PREPROCESS")
    if raw is None:
        return False
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _run_ffmpeg(cmd: list[str]) -> None:
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def normalize_audio(input_path: str) -> str:
    """
    Convert any audio format into mono 16kHz wav.
    """

    root, _ext = os.path.splitext(input_path)
    output_path = root + "_normalized.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        output_path
    ]

    _run_ffmpeg(cmd)

    return output_path


def normalize_audio_for_ht(input_path: str) -> str:
    """
    Apply only acoustic cleanup for HT ASR:
    - convert to mono
    - resample to 16kHz
    - apply a conservative loudness pass

    Linguistic cleanup belongs in text post-processing, not here.
    """

    root, _ext = os.path.splitext(input_path)
    output_path = root + "_ht_normalized.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-af", "loudnorm=I=-18:LRA=14:TP=-2.0:linear=true",
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        output_path
    ]

    _run_ffmpeg(cmd)

    return output_path


def trim_leading_trailing_silence(input_path: str) -> str:
    """
    Remove leading and trailing silence while preserving interior pauses.
    This is safe acoustic cleanup, not transcript normalization.
    """

    output_path = input_path.replace(".wav", "_trimmed.wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-af",
        (
            "silenceremove=start_periods=1:start_duration=0.3:start_threshold=-40dB,"
            "areverse,"
            "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-40dB,"
            "areverse"
        ),
        output_path
    ]

    _run_ffmpeg(cmd)

    return output_path


def preprocess_haitian_creole_audio(input_path: str) -> str:
    """
    Haitian Creole audio preprocessing should stay lightweight.

    Keep only acoustic cleanup that helps ASR directly:
    1. conservative loudness normalization
    2. mono / 16kHz conversion
    3. leading / trailing silence trim only

    Spelling normalization, Akademi cleanup, punctuation, and sentence repair
    should happen later in the text pipeline.
    """

    if not _ht_preprocess_enabled():
        return input_path

    normalized_path = normalize_audio_for_ht(input_path)

    try:
        trimmed_path = trim_leading_trailing_silence(normalized_path)
    except Exception:
        return normalized_path

    try:
        if os.path.exists(normalized_path):
            os.remove(normalized_path)
    except Exception:
        pass

    return trimmed_path
