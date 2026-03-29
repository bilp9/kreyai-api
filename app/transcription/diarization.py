from __future__ import annotations

import os
from typing import List, Dict, Optional

import torch
from pyannote.audio import Pipeline

_PIPELINE = None
_MODEL_ID = "pyannote/speaker-diarization-3.1"

# Ignore extremely short speaker bursts
MIN_SPEAKER_SEGMENT_SECONDS = 0.5


def get_diarization_configuration_error() -> Optional[str]:
    """
    Return a human-readable configuration error when diarization cannot start.
    """

    token = os.getenv("HF_TOKEN")

    if not token:
        return "HF_TOKEN environment variable not set"

    return None


def _normalize_diarization_error(error: Exception) -> RuntimeError:
    """
    Convert noisy Hugging Face/pyannote errors into a stable operator-facing message.
    """

    message = " ".join(str(arg) for arg in getattr(error, "args", ()) if arg).strip()
    if not message:
        message = str(error).strip()

    lowered = message.lower()

    if (
        "cannot access gated repo" in lowered
        or "access to model" in lowered
        or "not in the authorized list" in lowered
        or "403 client error" in lowered
    ):
        return RuntimeError(
            "HF_TOKEN does not have access to the required pyannote speaker diarization models. "
            "Grant the token access on Hugging Face for "
            "'pyannote/speaker-diarization-3.1' and "
            "'pyannote/speaker-diarization-community-1', then redeploy the worker."
        )

    if "401 client error" in lowered or "repository not found" in lowered:
        return RuntimeError(
            "HF_TOKEN is invalid or missing permission to load the pyannote speaker diarization models."
        )

    return RuntimeError(message or "Unable to load speaker diarization model")


def _iter_diarization_tracks(diarization_output):
    """
    Support both legacy pyannote Annotation outputs and newer DiarizeOutput objects.
    """

    if hasattr(diarization_output, "itertracks"):
        for turn, _, speaker in diarization_output.itertracks(yield_label=True):
            yield turn, speaker
        return

    speaker_diarization = getattr(diarization_output, "speaker_diarization", None)
    if speaker_diarization is not None:
        for turn, speaker in speaker_diarization:
            yield turn, speaker
        return

    raise RuntimeError(
        f"Unsupported diarization output type: {type(diarization_output).__name__}"
    )


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

        try:
            _PIPELINE = Pipeline.from_pretrained(
                _MODEL_ID,
                token=token,
            )
        except TypeError:
            try:
                _PIPELINE = Pipeline.from_pretrained(
                    _MODEL_ID,
                    use_auth_token=token,
                )
            except Exception as error:
                raise _normalize_diarization_error(error) from error
        except Exception as error:
            raise _normalize_diarization_error(error) from error

        # Optional GPU acceleration
        if torch.cuda.is_available():
            print("Using GPU for diarization")
            _PIPELINE.to(torch.device("cuda"))
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

    for turn, speaker in _iter_diarization_tracks(diarization):

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
