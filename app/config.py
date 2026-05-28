import os
from typing import Tuple


DEFAULT_PUBLIC_API_VERSION = "2.0.0"
DEFAULT_PUBLIC_LANGUAGES = ("auto", "en", "ht", "es", "fr", "pt")
LANGUAGE_LABELS = {
    "auto": "Auto Detect",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "pt": "Portuguese",
    "ht": "Haitian Creole",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
}


def get_public_api_version() -> str:
    return os.getenv("KREYAI_PUBLIC_API_VERSION", DEFAULT_PUBLIC_API_VERSION).strip() or DEFAULT_PUBLIC_API_VERSION


def get_public_language_options() -> Tuple[str, ...]:
    raw = os.getenv("KREYAI_PUBLIC_LANGUAGES", ",".join(DEFAULT_PUBLIC_LANGUAGES))
    items = []
    seen = set()

    for part in raw.split(","):
        value = part.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        items.append(value)

    if "auto" not in seen:
        items.insert(0, "auto")

    return tuple(items)


def get_public_supported_language_codes() -> Tuple[str, ...]:
    return tuple(language for language in get_public_language_options() if language != "auto")


def get_default_whisper_model_size() -> str:
    return os.getenv("WHISPER_MODEL_SIZE", "medium").strip() or "medium"


def get_language_label(code: str) -> str:
    normalized = str(code or "").strip().lower()
    if not normalized:
        return "Unknown"

    if normalized in LANGUAGE_LABELS:
        return LANGUAGE_LABELS[normalized]

    if len(normalized) <= 3:
        return normalized.upper()

    return normalized.replace("-", " ").title()


def build_openapi_yaml() -> str:
    api_version = get_public_api_version()
    language_options = ", ".join(get_public_language_options())
    public_languages = ", ".join(get_public_supported_language_codes())

    return f"""#=====================================
# PUBLIC API v2
#======================================

openapi: 3.0.3

info:
  title: KreyAI Transcription API
  description: >
    KreyAI public transcription API.
    Publicly supported languages in this deployment: {public_languages}.
  version: "{api_version}"
  contact:
    name: KreyAI
    url: https://www.kreyai.com

servers:
  - url: https://api.kreyai.com

security:
  - bearerAuth: []

paths:
  /v1/transcribe:
    post:
      summary: Transcribe an audio or video file
      operationId: transcribeFile
      security:
        - bearerAuth: []

      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              required:
                - file
              properties:
                file:
                  type: string
                  format: binary
                  description: Audio or video file (mp3, mp4, wav, m4a)
                language:
                  type: string
                  description: Language code or auto-detect
                  enum: [{language_options}]
                  default: auto
                format:
                  type: string
                  description: Output format
                  enum: [text, json, srt, vtt]
                  default: text
                speakers:
                  type: string
                  description: Speaker detection mode
                  enum: [auto, off]
                  default: off

      responses:
        "200":
          description: Transcription completed
        "400":
          description: Invalid request
        "401":
          description: Invalid or missing API key
        "413":
          description: File too large
        "429":
          description: Quota exceeded
        "500":
          description: Processing failed

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: API_KEY
"""
