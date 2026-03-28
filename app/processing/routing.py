from __future__ import annotations

import os
from typing import Dict

from app.constants import SpeakerMode


def resolve_processing_route(speaker_mode: str | None) -> Dict[str, object]:
    normalized = str(speaker_mode or SpeakerMode.UNSURE.value).strip().lower()

    if normalized not in {
        SpeakerMode.SINGLE.value,
        SpeakerMode.MULTI.value,
        SpeakerMode.UNSURE.value,
    }:
        normalized = SpeakerMode.UNSURE.value

    if normalized == SpeakerMode.SINGLE.value:
        return {
            "speaker_mode": SpeakerMode.SINGLE.value,
            "processing_tier": "standard",
            "execution_lane": "cpu",
            "requires_diarization": False,
            "worker_job_name": os.environ.get("CPU_WORKER_JOB_NAME", "kreyai-worker-cpu"),
            "worker_job_region": os.environ.get("CPU_WORKER_REGION", "us-central1"),
            "routing_reason": "single_speaker_standard",
        }

    return {
        "speaker_mode": normalized,
        "processing_tier": "premium",
        "execution_lane": "gpu",
        "requires_diarization": True,
        "worker_job_name": os.environ.get("GPU_WORKER_JOB_NAME", "kreyai-worker-gpu"),
        "worker_job_region": os.environ.get("GPU_WORKER_REGION", "us-east4"),
        "routing_reason": (
            "multi_speaker_premium"
            if normalized == SpeakerMode.MULTI.value
            else "unsure_speaker_premium"
        ),
    }
