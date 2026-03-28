from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.transcription.engine import TranscriptionConfig, transcribe_audio


SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".m4a",
    ".mov",
    ".wav",
    ".aac",
    ".flac",
    ".ogg",
    ".webm",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Haitian Creole eval transcription over a folder of approved files.",
    )
    parser.add_argument("input_dir", help="Directory containing approved audio/video files.")
    parser.add_argument(
        "--language",
        default="ht",
        help="Language code to force for eval runs. Defaults to ht.",
    )
    parser.add_argument(
        "--dataset-id",
        default="ht-batch",
        help="Dataset id used for eval artifact storage.",
    )
    parser.add_argument(
        "--gold-dir",
        default=None,
        help="Optional directory containing <audio_stem>.txt gold transcripts.",
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
    return parser


def _collect_inputs(root: Path) -> List[Path]:
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _mean(values: List[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        parser.error(f"Input directory not found: {input_dir}")

    files = _collect_inputs(input_dir)
    if not files:
        parser.error(f"No supported audio/video files found in: {input_dir}")

    os.environ["KREYAI_HT_EVAL_WRITES"] = "true"
    os.environ["KREYAI_HT_EVAL_DATASET"] = args.dataset_id
    if args.gold_dir:
        os.environ["KREYAI_HT_EVAL_GOLD_DIR"] = str(Path(args.gold_dir).expanduser().resolve())

    cfg = TranscriptionConfig(
        model_size=args.model_size or TranscriptionConfig().model_size,
        device=args.device,
        compute_type=args.compute_type,
    )

    runs: List[Dict[str, Any]] = []
    wers: List[float] = []
    cers: List[float] = []

    for input_path in files:
        os.environ["KREYAI_HT_EVAL_RUN_LABEL"] = input_path.stem

        result = transcribe_audio(
            str(input_path),
            cfg=cfg,
            language=args.language,
            debug=True,
            allow_promotion_writes=True,
        )

        debug = result.get("debug") or {}
        evaluation = debug.get("evaluation") or {}
        wer = None
        cer = None

        artifact_path = debug.get("eval_artifact_path")
        if artifact_path:
            artifact_file = Path(artifact_path)
            if artifact_file.exists():
                artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
                evaluation = artifact.get("evaluation") or {}
                word_error_rate = evaluation.get("word_error_rate") or {}
                char_error_rate = evaluation.get("character_error_rate") or {}
                wer = word_error_rate.get("error_rate")
                cer = char_error_rate.get("error_rate")

        if isinstance(wer, (int, float)):
            wers.append(float(wer))
        if isinstance(cer, (int, float)):
            cers.append(float(cer))

        runs.append(
            {
                "input_path": str(input_path),
                "eval_artifact_path": artifact_path,
                "language_detected": result.get("language_detected"),
                "language_final": result.get("language"),
                "speaker_ht_density": debug.get("speaker_ht_density"),
                "speaker_mode": debug.get("speaker_mode"),
                "a3_events_total": debug.get("a3_events_total"),
                "a3_reversals_total": debug.get("a3_reversals_total"),
                "word_error_rate": wer,
                "character_error_rate": cer,
            }
        )

    summary = {
        "dataset_id": args.dataset_id,
        "input_dir": str(input_dir),
        "file_count": len(runs),
        "average_word_error_rate": _mean(wers),
        "average_character_error_rate": _mean(cers),
        "runs": runs,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
