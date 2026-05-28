from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.transcription.formatting import apply_formatting, split_into_natural_paragraphs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a long transcript text file into a more readable paragraph layout.",
    )
    parser.add_argument("input_path", help="Path to the transcript text file.")
    parser.add_argument(
        "--output-path",
        default=None,
        help="Optional output path. Defaults to <input>.formatted.txt",
    )
    return parser


def default_output_path(input_path: Path) -> Path:
    if input_path.suffix.lower() == ".txt":
        return input_path.with_name(input_path.stem + ".formatted.txt")
    return input_path.with_name(input_path.name + ".formatted.txt")


def _split_on_existing_breaks(text: str) -> List[str]:
    blocks = re.split(r"\n\s*\n+", text.strip())
    return [block.strip() for block in blocks if block.strip()]


def render_readable(text: str) -> str:
    blocks = _split_on_existing_breaks(text)
    if not blocks:
        blocks = [text.strip()] if text.strip() else []

    rendered_blocks: List[str] = []
    for block in blocks:
        formatted = apply_formatting(block)
        paragraphs = split_into_natural_paragraphs(formatted)
        if paragraphs:
            rendered_blocks.append("\n\n".join(paragraphs))
        elif formatted:
            rendered_blocks.append(formatted)

    return ("\n\n".join(rendered_blocks).strip() + "\n") if rendered_blocks else ""


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

    original_text = input_path.read_text(encoding="utf-8")
    rendered_text = render_readable(original_text)
    output_path.write_text(rendered_text, encoding="utf-8")

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
