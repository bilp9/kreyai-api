from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.processing.audio_preprocess import normalize_audio
from app.transcription.engine import TranscriptionConfig, transcribe_audio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local Haitian Creole eval transcription and write an eval artifact.",
    )
    parser.add_argument("input_path", help="Path to the approved audio/video file.")
    parser.add_argument(
        "--language",
        default="ht",
        help="Language code to force for the eval run. Defaults to ht.",
    )
    parser.add_argument(
        "--dataset-id",
        default="ht-pilot",
        help="Dataset id used for eval artifact storage.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Optional run label. Defaults to the input file stem.",
    )
    parser.add_argument(
        "--gold-dir",
        default=None,
        help="Optional directory containing <audio_stem>.txt gold transcripts.",
    )
    parser.add_argument(
        "--gold-path",
        default=None,
        help="Optional explicit gold transcript path.",
    )
    parser.add_argument(
        "--model-size",
        default=None,
        help="Optional Whisper model size override.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Execution device for faster-whisper. Defaults to cpu.",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="faster-whisper compute type. Defaults to int8.",
    )
    parser.add_argument(
        "--preprocess-audio",
        action="store_true",
        help="Normalize the source to mono 16kHz wav before transcription.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    os.environ["KREYAI_HT_EVAL_WRITES"] = "true"
    os.environ["KREYAI_HT_EVAL_DATASET"] = args.dataset_id
    os.environ["KREYAI_HT_EVAL_RUN_LABEL"] = args.run_label or input_path.stem

    if args.gold_dir:
        os.environ["KREYAI_HT_EVAL_GOLD_DIR"] = str(Path(args.gold_dir).expanduser().resolve())
    if args.gold_path:
        os.environ["KREYAI_HT_EVAL_GOLD_PATH"] = str(Path(args.gold_path).expanduser().resolve())

    transcription_input = str(input_path)
    if args.preprocess_audio:
        transcription_input = normalize_audio(str(input_path))

    cfg = TranscriptionConfig(
        model_size=args.model_size or TranscriptionConfig().model_size,
        device=args.device,
        compute_type=args.compute_type,
    )

    result = transcribe_audio(
        transcription_input,
        cfg=cfg,
        language=args.language,
        debug=True,
        allow_promotion_writes=True,
    )

    debug = result.get("debug") or {}
    artifact_path = debug.get("eval_artifact_path")
    word_error_rate = None
    character_error_rate = None

    if artifact_path:
        artifact_file = Path(artifact_path)
        if artifact_file.exists():
            artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
            evaluation = artifact.get("evaluation") or {}
            word_error_rate = (evaluation.get("word_error_rate") or {}).get("error_rate")
            character_error_rate = (evaluation.get("character_error_rate") or {}).get("error_rate")

    payload = {
        "input_path": str(input_path),
        "transcription_input": transcription_input,
        "language_requested": result.get("language_requested"),
        "language_detected": result.get("language_detected"),
        "language_final": result.get("language"),
        "eval_artifact_path": artifact_path,
        "promotion_writes_enabled": debug.get("promotion_writes_enabled"),
        "speaker_ht_density": debug.get("speaker_ht_density"),
        "speaker_mode": debug.get("speaker_mode"),
        "a3_events_total": debug.get("a3_events_total"),
        "a3_reversals_total": debug.get("a3_reversals_total"),
        "word_error_rate": word_error_rate,
        "character_error_rate": character_error_rate,
        "preview_text": (result.get("text") or "")[:500],
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
