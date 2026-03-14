from __future__ import annotations

import os
from typing import List, Dict

import torch
from pyannote.audio import Pipeline

_PIPELINE = None

# Ignore extremely short speaker bursts
MIN_SPEAKER_SEGMENT_SECONDS = 0.5


def _get_pipeline() -> Pipeline:
    """
    Lazy-load the diarization pipeline once per worker.
    """

    global _PIPELINE

    if _PIPELINE is None:

        token = os.getenv("HF_TOKEN")

        if not token:
            raise RuntimeError("HF_TOKEN environment variable not set")

        print("Loading speaker diarization model...")

        _PIPELINE = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=token,
        )

        # Optional GPU acceleration
        if torch.cuda.is_available():
            print("Using GPU for diarization")
            _PIPELINE.to("cuda")
        else:
            print("Using CPU for diarization")

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

        start = float(turn.start)
        end = float(turn.end)
        duration = end - start

        # Filter very short speaker bursts (improves quality)
        if duration < MIN_SPEAKER_SEGMENT_SECONDS:
            continue

        segments.append(
            {
                "start": start,
                "end": end,
                "speaker": speaker,
            }
        )

    print(f"Diarization segments after filtering: {len(segments)}")

    return segments