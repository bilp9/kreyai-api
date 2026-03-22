# app/transcription/engine.py

# =================================================
# KreyAI Transcription Engine
# =================================================

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field, replace
from typing import Optional, List, Dict, Any
from collections import deque
from pathlib import Path

from faster_whisper import WhisperModel
from app.config import get_default_whisper_model_size

# -------------------------------------------------
# Akademi
# -------------------------------------------------
from app.transcription.akademi_normalize import AkademiNormalizer

# -------------------------------------------------
# Linguistic pipeline (HT-only)
# -------------------------------------------------
from app.transcription.normalize import normalize_creole
from app.transcription.contractions import expand_contractions
from app.transcription.dialect import normalize_dialect_variants
from app.transcription.lexical import apply_lexical_bias
from app.transcription.poslite import normalize_verb_phrases, normalize_pronoun_tma
from app.transcription.contextual import apply_contextual_corrections
from app.transcription.lexical_correction import apply_lexical_corrections
from app.transcription.technical import resolve_tech_phrases
from app.transcription.formatting import apply_formatting

# Confidence / hallucination (HT-only gates; harmless to compute but we keep HT-only)
from app.transcription.metrics import is_hallucinated
from app.transcription.confidence import split_segments_by_confidence, is_low_confidence

# Observability
from app.transcription.observability import PipelineMetrics

# HT density (HT-only)
from app.transcription.ht_density import (
    compute_ht_density,
    compute_ht_density_window,
    should_fire_a3,
)

# Promotion + reversal (HT-only)
from app.transcription.promotion import (
    load_promotion_db,
    save_promotion_db,
    record_fire,
    record_reversal,
)
from app.transcription.reversal import A3Event, detect_a3_reversals


# -------------------------------------------------
# Akademi singleton
# -------------------------------------------------
_AKADEMI: Optional[AkademiNormalizer] = None


def _load_akademi() -> Optional[AkademiNormalizer]:
    global _AKADEMI
    if _AKADEMI is not None:
        return _AKADEMI

    path = Path("data/akademi/processed/lexicon.json")
    if not path.exists():
        _AKADEMI = None
        return None

    lexicon = json.loads(path.read_text(encoding="utf-8"))
    _AKADEMI = AkademiNormalizer(lexicon)
    return _AKADEMI


# -------------------------------------------------
# Decoder prompt (HT-first)
# -------------------------------------------------
HT_DECODING_PROMPT = """
You are transcribing spoken Haitian Creole (Kreyòl Ayisyen).

Rules:
- Do NOT translate.
- Preserve code-switching (French / English).
- Do NOT invent words.
- Prefer standard Haitian Creole orthography when applicable.
"""


# -------------------------------------------------
# Gate thresholds (TUNED) — HT-only
# -------------------------------------------------
SPEAKER_NO_A3 = 0.18
SPEAKER_RESTRICTED_A3 = 0.30

WINDOW_MIN_FOR_A3 = 0.20
WINDOW_FULL_A3 = 0.35


# -------------------------------------------------
# Configuration
# -------------------------------------------------
@dataclass(frozen=True)
class TranscriptionConfig:
    model_size: str = field(default_factory=get_default_whisper_model_size)
    device: str = "cpu"
    compute_type: str = "int8"

    # Default to English for multi-language product;
    # HT pipeline activates only when language == "ht".
    language: str = "en"

    beam_size: int = 5
    temperature: float = 0.0
    vad_filter: bool = True
    condition_on_previous_text: bool = False

    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -0.7
    compression_ratio_threshold: float = 2.2
    repetition_penalty: float = 1.15
    no_repeat_ngram_size: int = 3

    initial_prompt: Optional[str] = None
    a3_window_segments: int = 6


# -------------------------------------------------
# Whisper model singleton
# -------------------------------------------------
_MODEL: Optional[WhisperModel] = None


def normalize_language_code(language: Optional[str]) -> Optional[str]:
    """
    Normalize user-facing language labels into engine-compatible codes.
    """

    if language is None:
        return None

    normalized = str(language).strip().lower()
    if not normalized:
        return None

    if normalized == "auto":
        return None

    ht_aliases = {
        "ht",
        "ht-ht",
        "haitian creole",
        "haitian-creole",
        "haitian kreyol",
        "haitian kreyòl",
        "kreyol",
        "kreyòl",
        "kreyol ayisyen",
        "kreyòl ayisyen",
    }
    if normalized in ht_aliases:
        return "ht"

    return normalized


def _get_model(cfg: TranscriptionConfig) -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        model_path = os.getenv("WHISPER_MODEL_PATH") or os.getenv("WHISPER_MODEL_SIZE") or cfg.model_size
        _MODEL = WhisperModel(
            model_path,
            device=cfg.device,
            compute_type=cfg.compute_type,
        )
    return _MODEL


def _speaker_gate(ht_density: float) -> str:
    if ht_density < SPEAKER_NO_A3:
        return "none"
    if ht_density < SPEAKER_RESTRICTED_A3:
        return "restricted"
    return "full_possible"


def _window_gate(metrics: Dict[str, Any]) -> str:
    ht = float(metrics.get("ht_density", 0.0))
    if ht < WINDOW_MIN_FOR_A3:
        return "none"
    if ht < WINDOW_FULL_A3:
        return "restricted"
    return "full"


# -------------------------------------------------
# Entry point
# -------------------------------------------------
def transcribe_audio(
    audio_path: str,
    cfg: Optional[TranscriptionConfig] = None,
    progress_cb=None,
    *,
    language: Optional[str] = None,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Returns:
      {
        "text": str,
        "segments": [{"start": float, "end": float, "text": str}],
        "debug": {...} | None
      }

    progress_cb:
      callable(pct:int, msg:str) -> None
    """

    cfg = cfg or TranscriptionConfig()

    # Optional per-call language override (from job record)
    normalized_language = normalize_language_code(language)
    if normalized_language:
        cfg = replace(cfg, language=normalized_language)
    engine_language = normalized_language or None

    def _progress(pct: int, msg: str):
        if callable(progress_cb):
            try:
                progress_cb(int(pct), str(msg))
            except Exception:
                pass  # never let progress reporting crash transcription

    _progress(10, "Loading model")
    model = _get_model(cfg)

    # Only load Akademi lexicon for Haitian Creole runs
    akademi = _load_akademi() if cfg.language == "ht" else None
    metrics = PipelineMetrics()

    _progress(20, "Transcribing audio")

    segments_iter, info = model.transcribe(
        audio_path,
        language=engine_language,
        task="transcribe", #enforcing transcription over translation 
        beam_size=cfg.beam_size,
        temperature=cfg.temperature,
        vad_filter=cfg.vad_filter,
        condition_on_previous_text=cfg.condition_on_previous_text,
        initial_prompt=HT_DECODING_PROMPT if cfg.language == "ht" else None,
        no_speech_threshold=cfg.no_speech_threshold,
        log_prob_threshold=cfg.log_prob_threshold,
        compression_ratio_threshold=cfg.compression_ratio_threshold,
        repetition_penalty=cfg.repetition_penalty,
        no_repeat_ngram_size=cfg.no_repeat_ngram_size,
        word_timestamps=True,
    )

    raw_segments: List[Dict[str, Any]] = []
    segments_list: List[Dict[str, Any]] = []

    for idx, seg in enumerate(segments_iter):
        if not getattr(seg, "text", None):
            continue

        text = seg.text.strip()
        words_payload: List[Dict[str, Any]] = []

        for word in getattr(seg, "words", None) or []:
            word_text = getattr(word, "word", None)
            if not word_text:
                continue

            word_start = getattr(word, "start", None)
            word_end = getattr(word, "end", None)

            words_payload.append(
                {
                    "word": str(word_text),
                    "start": float(word_start) if word_start is not None else None,
                    "end": float(word_end) if word_end is not None else None,
                    "probability": (
                        float(getattr(word, "probability"))
                        if getattr(word, "probability", None) is not None
                        else None
                    ),
                }
            )

        raw_segments.append(
            {
                "segment_index": idx,
                "raw_text": text,
                "text": text,
                "avg_logprob": getattr(seg, "avg_logprob", None),
                "hallucinated": bool(is_hallucinated(text)),
            }
        )

        segments_list.append(
            {
                "start": float(getattr(seg, "start", 0.0)),
                "end": float(getattr(seg, "end", 0.0)),
                "text": text,
                "words": words_payload,
            }
        )

    detected_language = normalize_language_code(getattr(info, "language", None))
    effective_language = detected_language or normalized_language or cfg.language
    is_ht_run = effective_language == "ht"

    if not raw_segments:
        _progress(100, "No speech detected")
        return {
            "text": "",
            "segments": [],
            "language": effective_language,
            "language_requested": normalized_language or "auto",
            "language_detected": detected_language,
            "debug": None,
        }

    # =================================================
    # NON-HT: minimal post-processing
    # =================================================
    if not is_ht_run:
        _progress(75, "Basic formatting")
        joined = " ".join(seg["text"] for seg in raw_segments)
        final_text = apply_formatting(joined).strip()

        for i in range(min(len(segments_list), len(raw_segments))):
            segments_list[i]["text"] = raw_segments[i]["text"]

        _progress(100, "Done")
        return {
            "text": final_text,
            "segments": segments_list,
            "language": effective_language,
            "language_requested": normalized_language or "auto",
            "language_detected": detected_language,
            "debug": None,
        }

    # =================================================
    # HT: Full KreyAI enhancement pipeline
    # =================================================

    _progress(35, "Post-processing (confidence gates)")
    split_segments_by_confidence(raw_segments)
    for seg in raw_segments:
        seg["low_confidence"] = is_low_confidence(seg)

    _progress(45, "Computing HT density")
    speaker_hits: List[float] = []
    for seg in raw_segments:
        d = compute_ht_density(seg["raw_text"])
        seg["ht_density_raw"] = d["ht_density"]
        speaker_hits.append(d["ht_density"])

    speaker_ht_density = sum(speaker_hits) / max(1, len(speaker_hits))
    speaker_mode = _speaker_gate(speaker_ht_density)

    _progress(60, "Linguistic normalization (pass 1)")
    for seg in raw_segments:
        text = seg["text"]
        confidence = seg.get("avg_logprob")

        # Akademi normalization (early)
        if akademi:
            text = akademi.normalize_text(text)

        text, _ = expand_contractions(text)
        text, _ = normalize_dialect_variants(text)

        # Pass 1: no A3
        text, _ = normalize_creole(text, a3_mode="none", metrics=None)

        text, _ = apply_lexical_bias(text)
        text, _ = normalize_verb_phrases(text)
        text, _ = normalize_pronoun_tma(text)
        text, _ = apply_contextual_corrections(text, confidence=confidence)
        text, _ = apply_lexical_corrections(text)

        # Akademi normalization (late)
        ak = _load_akademi()
        if ak:
            text = ak.normalize_text(text)

        seg["text"] = text

    _progress(75, "A3 window corrections")
    window = deque(maxlen=cfg.a3_window_segments)
    a3_events: List[A3Event] = []
    promo_db = load_promotion_db()

    for seg in raw_segments:
        window.append(seg["text"])
        window_text = " ".join(window)

        w_metrics = compute_ht_density_window(window_text)
        w_mode = _window_gate(w_metrics)

        if speaker_mode == "none" or w_mode == "none":
            continue
        if not should_fire_a3(w_metrics):
            continue

        a3_mode = (
            "full"
            if speaker_mode == "full_possible" and w_mode == "full"
            else "restricted"
        )

        before = seg["text"]
        after, a3_log = normalize_creole(before, a3_mode=a3_mode, metrics=None)

        if after != before and a3_log:
            seg["text"] = after
            for log_entry in a3_log:
                rule_id = log_entry.get("rule_id", str(log_entry))
                ev = A3Event(
                    rule_id=rule_id,
                    before=before,
                    after=after,
                    mode=a3_mode,
                    speaker_id="speaker_0",
                    segment_id=str(seg["segment_index"]),
                )
                a3_events.append(ev)
                record_fire(promo_db, rule_id=rule_id, mode=a3_mode)

    save_promotion_db(promo_db)

    _progress(88, "Formatting output")
    joined = " ".join(seg["text"] for seg in raw_segments)
    joined, _ = resolve_tech_phrases(joined, confidence=None)
    final_text = apply_formatting(joined).strip()

    # Keep timestamps but replace per-segment text with cleaned version
    for i in range(min(len(segments_list), len(raw_segments))):
        segments_list[i]["text"] = raw_segments[i]["text"]

    # A3 reversal detection
    reversed_events = detect_a3_reversals(a3_events=a3_events, final_text=final_text)
    if reversed_events:
        dbp = load_promotion_db()
        for ev in reversed_events:
            record_reversal(dbp, rule_id=ev.rule_id)
        save_promotion_db(dbp)

    _progress(100, "Done")

    return {
        "text": final_text,
        "segments": segments_list,
        "language": effective_language,
        "language_requested": normalized_language or "auto",
        "language_detected": detected_language,
        "debug": (
            {
                "language": effective_language,
                "language_requested": normalized_language or "auto",
                "language_detected": detected_language,
                "speaker_ht_density": speaker_ht_density,
                "speaker_mode": speaker_mode,
                "a3_events_total": len(a3_events),
                "a3_reversals_total": len(reversed_events),
                "pipeline_metrics": metrics.snapshot(),
            }
            if debug
            else None
        ),
    }
