from __future__ import annotations

import os
from typing import List, Dict

from pyannote.audio import Pipeline

_PIPELINE = None


def _get_pipeline() -> Pipeline:
    """
    Lazy-load the diarization pipeline once per worker.
    """
    global _PIPELINE

    if _PIPELINE is None:

        token = os.getenv("HF_TOKEN")

        if not token:
            raise RuntimeError("HF_TOKEN environment variable not set")

        _PIPELINE = Pipeline.from_pretrained(
            "pyannote/speaker-diarization",
            use_auth_token=token,
        )

    return _PIPELINE


def diarize_audio(audio_path: str) -> List[Dict]:
    """
    Run speaker diarization on a full audio file.

    Returns:
    [
        {
            "start": float,
            "end": float,
            "speaker": "SPEAKER_00"
        }
    ]
    """

    pipeline = _get_pipeline()

    diarization = pipeline(audio_path)

    segments: List[Dict] = []

    for turn, _, speaker in diarization.itertracks(yield_label=True):

        segments.append(
            {
                "start": float(turn.start),
                "end": float(turn.end),
                "speaker": speaker,
            }
        )

    return segments