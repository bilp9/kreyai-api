from app.transcription.normalize import normalize_creole
from app.transcription.dialects import normalize_dialect

def normalize_transcript(
    text: str,
    dialect: str = "ht",
):
    """
    Full normalization pipeline:
      1. Structural (apostrophes, spacing)
      2. Dialectal variants
    """
    base = normalize_creole(text)
    final, changes = normalize_dialect(base, dialect=dialect)

    return {
        "text": final,
        "dialect": dialect,
        "changes": changes,
    }
