# app/transcription/engine.py

# =================================================
# KreyAI Transcription Engine — API v1 (FROZEN)
# Any breaking change requires v2
# =================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple, Union
from collections import deque
from pathlib import Path
import json

from faster_whisper import WhisperModel

# -------------------------------------------------
# Akademi
# -------------------------------------------------
from app.transcription.akademi_normalize import AkademiNormalizer

# -------------------------------------------------
# Linguistic pipeline
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

# Confidence / hallucination
from app.transcription.metrics import is_hallucinated
from app.transcription.confidence import split_segments_by_confidence, is_low_confidence

# Observability
from app.transcription.observability import PipelineMetrics

# HT density
from app.transcription.ht_density import (
    compute_ht_density,
    compute_ht_density_window,
    should_fire_a3,
)

# Promotion + reversal
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
# Gate thresholds (TUNED)
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
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "ht"

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


def _get_model(cfg: TranscriptionConfig) -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = WhisperModel(
            cfg.model_size,
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
    *,
    debug: bool = False,
) -> Union[str, Tuple[str, Dict[str, Any]]]:

    cfg = cfg or TranscriptionConfig(initial_prompt=HT_DECODING_PROMPT)
    model = _get_model(cfg)
    akademi = _load_akademi()

    metrics = PipelineMetrics()

    segments, _ = model.transcribe(
        audio_path,
        language=cfg.language,
        beam_size=cfg.beam_size,
        temperature=cfg.temperature,
        vad_filter=cfg.vad_filter,
        condition_on_previous_text=cfg.condition_on_previous_text,
        initial_prompt=cfg.initial_prompt or HT_DECODING_PROMPT,
        no_speech_threshold=cfg.no_speech_threshold,
        log_prob_threshold=cfg.log_prob_threshold,
        compression_ratio_threshold=cfg.compression_ratio_threshold,
        repetition_penalty=cfg.repetition_penalty,
        no_repeat_ngram_size=cfg.no_repeat_ngram_size,
        word_timestamps=True,
    )

    raw_segments: List[Dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        if not seg.text:
            continue
        raw_segments.append(
            {
                "segment_index": idx,
                "raw_text": seg.text.strip(),
                "text": seg.text.strip(),
                "avg_logprob": seg.avg_logprob,
                "hallucinated": bool(is_hallucinated(seg.text)),
            }
        )

    if not raw_segments:
        return ("", {}) if debug else ""

    split_segments_by_confidence(raw_segments)
    for seg in raw_segments:
        seg["low_confidence"] = is_low_confidence(seg)

    # -------------------------------------------------
    # Speaker HT density
    # -------------------------------------------------
    speaker_hits = []
    for seg in raw_segments:
        d = compute_ht_density(seg["raw_text"])
        seg["ht_density_raw"] = d["ht_density"]
        speaker_hits.append(d["ht_density"])

    speaker_ht_density = sum(speaker_hits) / max(1, len(speaker_hits))
    speaker_mode = _speaker_gate(speaker_ht_density)

    # -------------------------------------------------
    # First pass (NO A3)
    # -------------------------------------------------
    for seg in raw_segments:
        text = seg["text"]
        confidence = seg["avg_logprob"]

        if akademi and cfg.language == "ht":
            text = akademi.normalize_text(text)

        text, _ = expand_contractions(text)
        text, _ = normalize_dialect_variants(text)
        text, _ = normalize_creole(text, a3_mode="none", metrics=None)
        text, _ = apply_lexical_bias(text)
        text, _ = normalize_verb_phrases(text)
        text, _ = normalize_pronoun_tma(text)
        text, _ = apply_contextual_corrections(text, confidence=confidence)
        text, _ = apply_lexical_corrections(text)

        text, _ = apply_lexical_bias(text)
        text, _ = normalize_verb_phrases(text)
        text, _ = normalize_pronoun_tma(text)
        text, _ = apply_contextual_corrections(text, confidence=confidence)
        text, _ = apply_lexical_corrections(text)

    # -----------------------------------------
    # Akademi normalization (read-only, late)
    # -----------------------------------------
        ak = _load_akademi()
        if ak:
            text = ak.normalize_text(text)

        seg["text"] = text


    # -------------------------------------------------
    # Windowed A3
    # -------------------------------------------------
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

    # -------------------------------------------------
    # Join + format
    # -------------------------------------------------
    joined = " ".join(seg["text"] for seg in raw_segments)
    joined, _ = resolve_tech_phrases(joined, confidence=None)
    final_text = apply_formatting(joined).strip()

    # -------------------------------------------------
    # A3 reversal detection
    # -------------------------------------------------
    reversed_events = detect_a3_reversals(
        a3_events=a3_events,
        final_text=final_text,
    )

    if reversed_events:
        db = load_promotion_db()
        for ev in reversed_events:
            record_reversal(db, rule_id=ev.rule_id)
        save_promotion_db(db)

    debug_payload = {
        "speaker_ht_density": speaker_ht_density,
        "speaker_mode": speaker_mode,
        "a3_events_total": len(a3_events),
        "a3_reversals_total": len(reversed_events),
        "pipeline_metrics": metrics.snapshot(),
    }

    return {
    "text": final_text,
    "segments": segments_list
}

