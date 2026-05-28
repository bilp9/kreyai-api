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
from app.config_ht import HT_ENABLE_PROMPT, ht_use_thin_pipeline

# -------------------------------------------------
# Akademi
# -------------------------------------------------
from app.transcription.akademi_normalize import AkademiNormalizer
from app.transcription.lexicon_store import load_learned_lexicon

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
from app.transcription.formatting_light import apply_light_formatting, minimal_postprocess_ht
from app.transcription.code_switch import (
    shield_code_switch_spans,
    restore_code_switch_spans,
    has_unrestored_code_switch_placeholders,
)

# Confidence / hallucination (HT-only gates; harmless to compute but we keep HT-only)
from app.transcription.metrics import is_hallucinated, is_known_subtitle_hallucination
from app.transcription.confidence import (
    split_segments_by_confidence,
    is_low_confidence,
    get_confidence_tier,
)

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
from app.transcription.eval_artifacts import write_eval_artifact


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
    for word in load_learned_lexicon():
        lexicon.setdefault(word, 1.0)
    _AKADEMI = AkademiNormalizer(lexicon)
    return _AKADEMI


# -------------------------------------------------
# Decoder prompt (HT-first)
# -------------------------------------------------
# Disabled by default because long instruction-style prompts can leak
# into the transcript itself on lower-confidence runs. If we want to
# experiment with prompting again, keep it short and bias-only.
HT_DECODING_PROMPT = (
    "Haitian Creole transcription only; no translation; keep French/English code-switching; "
    "no invented words; standard Haitian Creole spelling."
)


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
    best_of: int = 5
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
# Whisper model cache
# -------------------------------------------------
_MODELS: Dict[str, WhisperModel] = {}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_bool_env(name: str) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _float_env(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _temperature_env(name: str) -> Optional[Any]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None

    value = raw.strip()
    if "," in value:
        temps = []
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                temps.append(float(item))
            except ValueError:
                return None
        return temps or None

    try:
        return float(value)
    except ValueError:
        return None


def _promotion_writes_enabled(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return explicit
    return _bool_env("KREYAI_HT_EVAL_WRITES", default=False)


def _ht_decoder_prompt() -> Optional[str]:
    if not HT_ENABLE_PROMPT:
        return None
    if not _bool_env("KREYAI_HT_USE_DECODER_PROMPT", default=False):
        return None
    prompt = os.getenv("KREYAI_HT_DECODER_PROMPT", "").strip()
    if prompt:
        return prompt
    return HT_DECODING_PROMPT


def _apply_ht_decode_overrides(cfg: TranscriptionConfig) -> TranscriptionConfig:
    if cfg.language != "ht":
        return cfg

    # HT test runs were noticeably better with raw Whisper behavior. Faster
    # Whisper's VAD and the generic no-speech threshold can drop soft/overlapped
    # Creole speech, so default HT to model-side segmentation and a less
    # aggressive no-speech gate unless an experiment explicitly overrides them.
    updates: Dict[str, Any] = {
        "vad_filter": False,
    }

    beam_size = _int_env("KREYAI_HT_BEAM_SIZE")
    if beam_size is not None:
        updates["beam_size"] = beam_size

    best_of = _int_env("KREYAI_HT_BEST_OF")
    if best_of is not None:
        updates["best_of"] = best_of

    temperature = _temperature_env("KREYAI_HT_TEMPERATURE")
    if temperature is not None:
        updates["temperature"] = temperature

    no_speech_threshold = _float_env("KREYAI_HT_NO_SPEECH_THRESHOLD")
    if no_speech_threshold is not None:
        updates["no_speech_threshold"] = no_speech_threshold

    log_prob_threshold = _float_env("KREYAI_HT_LOG_PROB_THRESHOLD")
    if log_prob_threshold is not None:
        updates["log_prob_threshold"] = log_prob_threshold

    compression_ratio_threshold = _float_env("KREYAI_HT_COMPRESSION_RATIO_THRESHOLD")
    if compression_ratio_threshold is not None:
        updates["compression_ratio_threshold"] = compression_ratio_threshold

    repetition_penalty = _float_env("KREYAI_HT_REPETITION_PENALTY")
    if repetition_penalty is not None:
        updates["repetition_penalty"] = repetition_penalty

    no_repeat_ngram_size = _int_env("KREYAI_HT_NO_REPEAT_NGRAM_SIZE")
    if no_repeat_ngram_size is not None:
        updates["no_repeat_ngram_size"] = no_repeat_ngram_size

    condition_on_previous_text = os.getenv("KREYAI_HT_CONDITION_ON_PREVIOUS_TEXT")
    if condition_on_previous_text is not None and condition_on_previous_text.strip():
        updates["condition_on_previous_text"] = (
            condition_on_previous_text.strip().lower() in {"1", "true", "yes", "on"}
        )

    vad_filter = _optional_bool_env("KREYAI_HT_VAD_FILTER")
    if vad_filter is not None:
        updates["vad_filter"] = vad_filter

    if not updates:
        return cfg

    return replace(cfg, **updates)


def _eval_dataset_id() -> Optional[str]:
    value = os.getenv("KREYAI_HT_EVAL_DATASET", "").strip()
    return value or None


def _eval_run_label(audio_path: str) -> str:
    env_value = os.getenv("KREYAI_HT_EVAL_RUN_LABEL", "").strip()
    if env_value:
        return env_value
    return Path(audio_path).stem or "eval-run"


def _load_eval_gold_text(audio_path: str) -> Optional[str]:
    explicit_path = os.getenv("KREYAI_HT_EVAL_GOLD_PATH", "").strip()
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return path.read_text(encoding="utf-8")

    gold_dir = os.getenv("KREYAI_HT_EVAL_GOLD_DIR", "").strip()
    if not gold_dir:
        return None

    path = Path(gold_dir) / f"{Path(audio_path).stem}.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


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


def _resolve_model_path(cfg: TranscriptionConfig) -> str:
    if cfg.language == "ht":
        return (
            os.getenv("WHISPER_MODEL_PATH_HT")
            or os.getenv("WHISPER_MODEL_SIZE_HT")
            or "large-v3"
        )

    return os.getenv("WHISPER_MODEL_PATH") or os.getenv("WHISPER_MODEL_SIZE") or cfg.model_size


def _get_model(cfg: TranscriptionConfig) -> WhisperModel:
    model_path = _resolve_model_path(cfg)
    cache_key = f"{model_path}|{cfg.device}|{cfg.compute_type}"

    model = _MODELS.get(cache_key)
    if model is None:
        model = WhisperModel(
            model_path,
            device=cfg.device,
            compute_type=cfg.compute_type,
        )
        _MODELS[cache_key] = model
    return model


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


def _refine_ht_segment_second_pass(
    text: str,
    *,
    confidence: Optional[float],
    confidence_tier: str,
    akademi: Optional[AkademiNormalizer],
) -> str:
    """
    Conservative HT-only second pass.

    Goals:
    - touch only low-confidence segments
    - be more assertive on `low`
    - stay extra conservative on `review`
    """

    refined = text

    if confidence_tier not in {"low", "review"}:
        return refined

    refined, code_switch_replacements = shield_code_switch_spans(refined)

    if akademi:
        refined = akademi.normalize_text(refined)

    refined, _ = expand_contractions(refined)
    refined, _ = normalize_dialect_variants(refined)

    if confidence_tier == "low":
        refined, _ = normalize_creole(refined, a3_mode="restricted", metrics=None)
        refined, _ = apply_lexical_bias(refined)
        refined, _ = normalize_verb_phrases(refined)
        refined, _ = normalize_pronoun_tma(refined)
        refined, _ = apply_contextual_corrections(refined, confidence=confidence)
        refined, _ = apply_lexical_corrections(refined)
    else:
        # `review` segments are the riskiest: bias toward orthography cleanup only.
        refined, _ = normalize_creole(refined, a3_mode="none", metrics=None)
        refined, _ = apply_contextual_corrections(refined, confidence=confidence)

    if akademi:
        refined = akademi.normalize_text(refined)

    return restore_code_switch_spans(refined, code_switch_replacements)


def transcribe_ht_raw(
    *,
    raw_segments: List[Dict[str, Any]],
    segments_list: List[Dict[str, Any]],
    effective_language: str,
    normalized_language: Optional[str],
    detected_language: Optional[str],
    debug: bool,
) -> Dict[str, Any]:
    filtered_raw_segments: List[Dict[str, Any]] = []
    filtered_segments_list: List[Dict[str, Any]] = []

    for raw_segment, segment in zip(raw_segments, segments_list):
        if is_known_subtitle_hallucination(raw_segment.get("text") or ""):
            continue
        filtered_raw_segments.append(raw_segment)
        filtered_segment = dict(segment)
        filtered_segment["text"] = apply_light_formatting(raw_segment["text"], language="ht")
        filtered_segments_list.append(filtered_segment)

    joined = " ".join(seg["text"] for seg in filtered_raw_segments)
    final_text = minimal_postprocess_ht(joined).strip()

    if has_unrestored_code_switch_placeholders(final_text):
        raise ValueError("Unrestored code-switch placeholder detected in HT transcript")

    debug_payload = (
        {
            "language": effective_language,
            "language_requested": normalized_language or "auto",
            "language_detected": detected_language,
            "pipeline_mode": "thin",
        }
        if debug
        else None
    )

    return {
        "text": final_text,
        "segments": filtered_segments_list,
        "language": effective_language,
        "language_requested": normalized_language or "auto",
        "language_detected": detected_language,
        "debug": debug_payload,
    }


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
    allow_promotion_writes: Optional[bool] = None,
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
    promotion_writes_enabled = _promotion_writes_enabled(allow_promotion_writes)

    # Optional per-call language override (from job record)
    normalized_language = normalize_language_code(language)
    if normalized_language:
        cfg = replace(cfg, language=normalized_language)
    cfg = _apply_ht_decode_overrides(cfg)
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
        best_of=cfg.best_of,
        temperature=cfg.temperature,
        vad_filter=cfg.vad_filter,
        condition_on_previous_text=cfg.condition_on_previous_text,
        initial_prompt=_ht_decoder_prompt() if cfg.language == "ht" else None,
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
                "no_speech_prob": getattr(seg, "no_speech_prob", None),
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

    raw_segments_snapshot = [
        {
            "segment_index": seg["segment_index"],
            "raw_text": seg["raw_text"],
            "text": seg["text"],
            "avg_logprob": seg["avg_logprob"],
            "no_speech_prob": seg.get("no_speech_prob"),
            "hallucinated": seg["hallucinated"],
        }
        for seg in raw_segments
    ]

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
        final_text = apply_formatting(joined, language=effective_language).strip()

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
    if ht_use_thin_pipeline():
        return transcribe_ht_raw(
            raw_segments=raw_segments,
            segments_list=segments_list,
            effective_language=effective_language,
            normalized_language=normalized_language,
            detected_language=detected_language,
            debug=debug,
        )

    _progress(35, "Post-processing (confidence gates)")
    split_segments_by_confidence(raw_segments)
    for seg in raw_segments:
        seg["confidence_tier"] = get_confidence_tier(seg)
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
        text, code_switch_replacements = shield_code_switch_spans(text)

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

        seg["text"] = restore_code_switch_spans(text, code_switch_replacements)

    _progress(75, "A3 window corrections")
    window = deque(maxlen=cfg.a3_window_segments)
    a3_events: List[A3Event] = []
    promo_db = load_promotion_db() if promotion_writes_enabled else None

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
                if promo_db is not None:
                    record_fire(promo_db, rule_id=rule_id, mode=a3_mode)

    if promo_db is not None:
        save_promotion_db(promo_db)

    _progress(84, "Second-pass refinement")
    second_pass_segments = 0
    for seg in raw_segments:
        confidence_tier = str(seg.get("confidence_tier") or "medium")
        if confidence_tier not in {"low", "review"}:
            continue

        before = seg["text"]
        after = _refine_ht_segment_second_pass(
            before,
            confidence=seg.get("avg_logprob"),
            confidence_tier=confidence_tier,
            akademi=akademi,
        )
        if after != before:
            seg["text"] = after
        second_pass_segments += 1

    _progress(88, "Formatting output")
    joined = " ".join(seg["text"] for seg in raw_segments)
    joined, _ = resolve_tech_phrases(joined, confidence=None)
    final_text = apply_formatting(joined, language=effective_language).strip()

    # Keep timestamps but replace per-segment text with cleaned version
    for i in range(min(len(segments_list), len(raw_segments))):
        segments_list[i]["text"] = raw_segments[i]["text"]

    # A3 reversal detection
    reversed_events = detect_a3_reversals(a3_events=a3_events, final_text=final_text)
    if reversed_events and promotion_writes_enabled:
        dbp = load_promotion_db()
        for ev in reversed_events:
            record_reversal(dbp, rule_id=ev.rule_id)
        save_promotion_db(dbp)

    _progress(100, "Done")

    debug_payload = (
        {
            "language": effective_language,
            "language_requested": normalized_language or "auto",
            "language_detected": detected_language,
            "speaker_ht_density": speaker_ht_density,
            "speaker_mode": speaker_mode,
            "promotion_writes_enabled": promotion_writes_enabled,
            "a3_events_total": len(a3_events),
            "a3_reversals_total": len(reversed_events),
            "second_pass_segments_total": second_pass_segments,
            "pipeline_metrics": metrics.snapshot(),
        }
        if debug
        else None
    )

    eval_artifact_path: Optional[str] = None

    if promotion_writes_enabled:
        try:
            artifact_path = write_eval_artifact(
                audio_path=audio_path,
                language_requested=normalized_language or "auto",
                language_detected=detected_language,
                language_final=effective_language,
                raw_segments=raw_segments_snapshot,
                cleaned_segments=[
                    {
                        "segment_index": seg["segment_index"],
                        "text": seg["text"],
                        "ht_density_raw": seg.get("ht_density_raw"),
                        "confidence_tier": seg.get("confidence_tier"),
                        "low_confidence": seg.get("low_confidence"),
                    }
                    for seg in raw_segments
                ],
                final_text=final_text,
                debug_payload=debug_payload,
                gold_text=_load_eval_gold_text(audio_path),
                dataset_id=_eval_dataset_id(),
                run_label=_eval_run_label(audio_path),
                approved_for_improvement=promotion_writes_enabled,
            )
            eval_artifact_path = str(artifact_path)
        except Exception:
            pass

    if debug_payload is not None:
        debug_payload["eval_artifact_path"] = eval_artifact_path

    return {
        "text": final_text,
        "segments": segments_list,
        "language": effective_language,
        "language_requested": normalized_language or "auto",
        "language_detected": detected_language,
        "debug": debug_payload,
    }
