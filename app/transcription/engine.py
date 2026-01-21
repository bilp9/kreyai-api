from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict

from faster_whisper import WhisperModel

# -------------------------------------------------------------------
# Pipeline imports (ORDER IS CONTRACTUAL)
# -------------------------------------------------------------------

# A1 — contraction cleanup (m’ap → m ap)
from app.transcription.normalization import normalize_contractions

# A5 — dialect variants (nap → n ap)
from app.transcription.normalization import normalize_dialect_variants

# B1 — lexical bias
from app.transcription.lexical import apply_lexical_bias

# C3 / C3.1 — verb phrase + pronoun/TMA normalization
from app.transcription.poslite import (
    normalize_verb_phrases,
    normalize_pronoun_tma,
)

# C2 — block French intrusions
from app.transcription.contextual import apply_contextual_corrections

# Controlled lexical correction (late & conservative)
from app.transcription.lexical_correction import apply_lexical_corrections

# Confidence utilities
from app.transcription.confidence import (
    split_segments_by_confidence,
    is_low_confidence,
)

# Confidence-weighted correction
from app.transcription.corrector import apply_confidence_weighted_correction
from app.transcription.technical import resolve_tech_phrases

# FINAL formatting
from app.transcription.formatting import apply_formatting


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

@dataclass(frozen=True)
class TranscriptionConfig:
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "ht"
    beam_size: int = 5
    temperature: float = 0.0
    vad_filter: bool = True
    condition_on_previous_text: bool = False
    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -1.0
    initial_prompt: Optional[str] = None


_DEFAULT_PROMPT_HT = (
    "Transcribe in Haitian Creole (Kreyòl Ayisyen) ONLY. Do not translate. "
    "Use official Haitian Creole spelling and spacing. "
    "Prefer: 'm ap', 'm te', 'm pral', 'n ap' (or 'nap'), "
    "'pa', 'pou', 'mwen', 'ou', 'li', 'nou', 'yo'. "
    "Keep Haitian Creole structure; do not switch to French unless the speaker clearly does."
)


# -------------------------------------------------------------------
# Whisper model singleton
# -------------------------------------------------------------------

_MODEL: Optional[WhisperModel] = None


def _get_model(cfg: TranscriptionConfig) -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = WhisperModel(
            cfg.model_size,
            device=cfg.device,
            compute_type=cfg.compute_type,
        )
    return _MODEL


# -------------------------------------------------------------------
# Transcription entry point
# -------------------------------------------------------------------

def transcribe_audio(
    audio_path: str,
    cfg: Optional[TranscriptionConfig] = None,
) -> str:
    """
    Transcribe audio into Haitian Creole text and apply
    confidence-aware normalization, biasing, correction,
    and final formatting.
    """

    cfg = cfg or TranscriptionConfig(
        initial_prompt=_DEFAULT_PROMPT_HT
    )

    model = _get_model(cfg)

    segments, info = model.transcribe(
        audio_path,
        language=cfg.language,
        beam_size=cfg.beam_size,
        temperature=cfg.temperature,
        vad_filter=cfg.vad_filter,
        condition_on_previous_text=cfg.condition_on_previous_text,
        initial_prompt=cfg.initial_prompt,
        no_speech_threshold=cfg.no_speech_threshold,
        log_prob_threshold=cfg.log_prob_threshold,
        word_timestamps=True,
    )

    # -------------------------------------------------------------------
    # 1) Capture raw segments with confidence
    # -------------------------------------------------------------------

    raw_segments: List[Dict] = []

    for seg in segments:
        if not seg.text:
            continue

        raw_segments.append({
            "text": seg.text.strip(),
            "avg_logprob": seg.avg_logprob,
            "no_speech_prob": seg.no_speech_prob,
        })

    if not raw_segments:
        return ""

    # -------------------------------------------------------------------
    # 2) Confidence classification
    # -------------------------------------------------------------------

    high_conf, low_conf = split_segments_by_confidence(raw_segments)

    for seg in raw_segments:
        seg["low_confidence"] = is_low_confidence(seg)

    # -------------------------------------------------------------------
    # 3) Segment-level linguistic pipeline
    # -------------------------------------------------------------------

    for seg in raw_segments:
        text = seg["text"]
        confidence = seg["avg_logprob"]

        # A1 — contraction cleanup
        text, _ = normalize_contractions(text)

        # A5 — dialect variants
        text, _ = normalize_dialect_variants(text)

        # B1 — lexical bias
        text, _ = apply_lexical_bias(text)

        # C3 — verb phrase detection
        text, _ = normalize_verb_phrases(text)

        # C3.1 — pronoun + TMA normalization
        text, _ = normalize_pronoun_tma(text)

        # C2 — block French intrusions (confidence-gated)
        if confidence is not None and confidence > -0.9:
            text, _ = apply_contextual_corrections(
                text,
                confidence=confidence,
            )

        # Controlled lexical correction (late & conservative)
        text, _ = apply_lexical_corrections(text)

        seg["text"] = text

    # -------------------------------------------------------------------
    # 4) Confidence-weighted technical correction
    # -------------------------------------------------------------------

    final_text, correction_log = apply_confidence_weighted_correction(
        raw_segments,
        correction_fn=resolve_tech_phrases,
    )

    # -------------------------------------------------------------------
    # 5) FINAL formatting (ALWAYS LAST)
    # -------------------------------------------------------------------

    final_text = apply_formatting(final_text)

    return final_text
