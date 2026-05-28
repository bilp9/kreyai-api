from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.transcription.akademi_normalize import AkademiNormalizer
from app.transcription.lexicon_store import load_learned_lexicon


AKADEMI_LEXICON_PATH = ROOT / "data" / "akademi" / "processed" / "lexicon.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply conservative Akademi spelling cleanup to a Haitian Creole transcript.",
    )
    parser.add_argument("input_path", help="Path to the finished transcript text file.")
    parser.add_argument(
        "--output-path",
        default=None,
        help="Optional output path. Defaults to <input>.akademi-cleaned.txt",
    )
    return parser


def load_akademi_normalizer() -> AkademiNormalizer:
    lexicon = json.loads(AKADEMI_LEXICON_PATH.read_text(encoding="utf-8"))
    for word in load_learned_lexicon():
        lexicon.setdefault(word, 1.0)
    return AkademiNormalizer(lexicon)


def default_output_path(input_path: Path) -> Path:
    if input_path.suffix.lower() == ".txt":
        return input_path.with_name(input_path.stem + ".akademi-cleaned.txt")
    return input_path.with_name(input_path.name + ".akademi-cleaned.txt")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    output_path = (
        Path(args.output_path).expanduser().resolve()
        if args.output_path
        else default_output_path(input_path)
    )

    normalizer = load_akademi_normalizer()
    original_text = input_path.read_text(encoding="utf-8")
    cleaned_text = normalizer.normalize_text(original_text)

    output_path.write_text(cleaned_text, encoding="utf-8")

    changed = 0 if cleaned_text == original_text else 1
    print(
        json.dumps(
            {
                "input_path": str(input_path),
                "output_path": str(output_path),
                "changed": bool(changed),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
