from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TOKEN_FIXES = {
    "nonpam": "non pam",
    "npral": "n pral",
    "mwe": "mwen",
    "yong": "yon",
    "aveke": "avèk",
    "avek": "avèk",
    "problems": "pwoblèm",
    "metin": "medsin",
    "realiti": "reyalite",
}

AKADEMI_DICT = {
    "lii": "li",
    "sakapfet": "sa k ap fèt",
    "nap": "n ap",
    "poutor": "pita",
}

DO_NOT_TOUCH = {"amazon", "whatsapp", "social", "medicine"}


def basic_cleanup(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def apply_token_fixes(text: str) -> str:
    for wrong, correct in TOKEN_FIXES.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", correct, text)
    return text


def fix_contractions(text: str) -> str:
    text = re.sub(r"\bm'ap\b", "m ap", text)
    text = re.sub(r"\bn'ap\b", "n ap", text)
    text = re.sub(r"\bk'ap\b", "k ap", text)
    text = re.sub(r"\bt'ap\b", "t ap", text)
    return text


def akademi_normalize(text: str) -> str:
    words = text.split()
    normalized = []

    for word in words:
        clean_word = re.sub(r"[^\wàâèéêëîïôòùûüç'-]", "", word)
        lower_word = clean_word.lower()

        if lower_word in DO_NOT_TOUCH:
            normalized.append(word)
        elif lower_word in AKADEMI_DICT:
            replacement = AKADEMI_DICT[lower_word]
            normalized.append(word.replace(clean_word, replacement))
        else:
            normalized.append(word)

    return " ".join(normalized)


def remove_repetition(text: str) -> str:
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text)
    return text


def reconstruct_sentences(text: str) -> str:
    text = re.sub(r"\s*([.!?])\s*", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()

    sentences = re.split(r"[.!?]+", text)
    sentences = [sentence.strip().capitalize() for sentence in sentences if sentence.strip()]

    if not sentences:
        return ""

    return ". ".join(sentences) + "."


def format_paragraphs(text: str) -> str:
    sentences = [sentence.strip() for sentence in text.split(". ") if sentence.strip()]
    paragraph = ""
    output = []

    for index, sentence in enumerate(sentences):
        paragraph += sentence.rstrip(".") + ". "
        if (index + 1) % 2 == 0:
            output.append(paragraph.strip())
            paragraph = ""

    if paragraph:
        output.append(paragraph.strip())

    return "\n\n".join(output).strip() + "\n"


def post_process(text: str) -> str:
    text = basic_cleanup(text)
    text = apply_token_fixes(text)
    text = fix_contractions(text)
    text = akademi_normalize(text)
    text = remove_repetition(text)
    text = reconstruct_sentences(text)
    text = format_paragraphs(text)
    return text


def default_output_path(input_path: Path) -> Path:
    if input_path.suffix.lower() == ".txt":
        return input_path.with_name(input_path.stem + ".readable.txt")
    return input_path.with_name(input_path.name + ".readable.txt")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Post-process a Haitian Creole transcript into a more readable local text file.",
    )
    parser.add_argument("input_path", help="Path to the transcript text file.")
    parser.add_argument(
        "--output-path",
        default=None,
        help="Optional output path. Defaults to <input>.readable.txt",
    )
    return parser


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
    cleaned_text = post_process(original_text)
    output_path.write_text(cleaned_text, encoding="utf-8")

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
