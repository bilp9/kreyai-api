from app.constants import PROCESS_ATTEMPT_TIMEOUT_SECONDS
from app.processing.runner import _transcription_timeout_seconds, save_outputs
from app.services.ht_llm_review import (
    DEFAULT_PROMPT,
    _build_input,
    _extract_chunk_payload,
    _normalize_glossary_terms,
    _postprocess_review_text,
)
from app.transcription.ht_cleanup_pipeline import run_ht_cleanup_pipeline
from app.transcription.formatting_light import minimal_postprocess_ht


class FakeStorage:
    def __init__(self):
        self.outputs = {}

    def save_output(self, job_id, filename, content, content_type):
        self.outputs[(job_id, filename)] = {
            "content": content,
            "content_type": content_type,
        }


def test_ht_timeout_budget_scales_for_medium_form_audio():
    timeout_seconds = _transcription_timeout_seconds(
        language="ht",
        audio_duration_seconds=1939.017125,
    )

    assert timeout_seconds > PROCESS_ATTEMPT_TIMEOUT_SECONDS
    assert timeout_seconds == 3023


def test_ht_cleanup_preserves_code_switched_english_words():
    text = "we created Project Saint-Anne officially as a 501c3 non profit organization with problems."

    cleaned = run_ht_cleanup_pipeline(text)

    assert "we created Project Saint-Anne officially" in cleaned
    assert "non profit organization" in cleaned
    assert "problems" in cleaned
    assert "pwoblèm" not in cleaned


def test_ht_clean_output_preserves_speaker_timestamp_blocks():
    storage = FakeStorage()
    result = {
        "language": "ht",
        "text": "nanpam seyon test we created Project Saint-Anne officially.",
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "speaker": "SPEAKER_00",
                "text": "nanpam seyon test",
            },
            {
                "start": 2.5,
                "end": 5.0,
                "speaker": "SPEAKER_01",
                "text": "we created Project Saint-Anne officially",
            },
        ],
        "debug": {"pipeline_mode": "thin"},
    }

    save_outputs(storage, "KR-HT", result)

    clean_text = storage.outputs[("KR-HT", "transcript.clean.txt")]["content"].decode("utf-8")
    raw_text = storage.outputs[("KR-HT", "transcript.raw.txt")]["content"].decode("utf-8")

    assert "SPEAKER_00 (00:00:00)" in clean_text
    assert "SPEAKER_01 (00:00:02)" in clean_text
    assert "non pa m se yon test" in clean_text
    assert "we created Project Saint-Anne officially" in clean_text
    assert "SPEAKER_00 (00:00:00)" in raw_text


def test_ht_light_formatting_adds_readable_breaks_without_rewriting_code_switching():
    text = (
        "Bonjou, bonjou tout moun non pa m se Yurian Seloti lwi jodi a mwen kontan avek nou. "
        "Avek yon bel ekip kote n pral gade ansam problem ke profesyonel sante yo avek pasyon yo ap fe fas an Haiti. "
        "Donk jodi a se yon plezi pou nou pral pale ansam epi mete men an pat la. "
        "Mwen gen avek mwen yon bel ekip Mwen gen Chevalier J Mwen gen Gerson Moras "
        "Bonjour ekip Non pa m se Erji Chevalier mwen se medisen."
    )

    formatted = minimal_postprocess_ht(text)

    assert "Donk jodi a" in formatted
    assert ". Donk jodi a" in formatted
    assert "Bonjour ekip" in formatted
    assert "Non pa m se Erji Chevalier" in formatted
    assert "problem" in formatted
    assert "pwoblèm" not in formatted
    assert "profesyonel sante" in formatted
    assert "\n\n" in formatted


def test_ht_light_formatting_does_not_touch_speaker_timestamp_lines():
    storage = FakeStorage()
    result = {
        "language": "ht",
        "text": "Donk jodi a se yon plezi.",
        "segments": [
            {
                "start": 4.0,
                "end": 8.0,
                "speaker": "SPEAKER_00",
                "text": "Donk jodi a se yon plezi pou nou pale ansam. Bonjour ekip non pa m se Erji.",
            },
        ],
        "debug": {"pipeline_mode": "thin"},
    }

    save_outputs(storage, "KR-HT-PUNCT", result)

    clean_text = storage.outputs[("KR-HT-PUNCT", "transcript.clean.txt")]["content"].decode("utf-8")

    assert clean_text.startswith("SPEAKER_00 (00:00:04)\n")
    assert "Bonjour ekip" in clean_text


def test_ht_review_prompt_includes_glossary_terms():
    glossary_terms = _normalize_glossary_terms(
        ["Project Saint-Anne", "project saint-anne", "501c3", "Randy Gwonaï", "x" * 200]
    )

    messages = _build_input(
        DEFAULT_PROMPT,
        "we created Project Sentan officially as a 501c3",
        0,
        1,
        glossary_terms=glossary_terms,
    )

    system_message = messages[0]["content"]
    user_message = messages[1]["content"]

    assert glossary_terms == ["Project Saint-Anne", "501c3", "Randy Gwonaï", "x" * 120]
    assert "Known terms and names" in system_message
    assert "- Project Saint-Anne" in system_message
    assert "- 501c3" in system_message
    assert "do not invent glossary terms" in system_message
    assert "Preserve transcript structure exactly" in system_message
    assert "SPEAKER_00 (00:00:00)" in system_message
    assert "Keep code-switched English/French" in user_message
    assert "Only fix obvious Haitian Creole spelling" in system_message
    assert "Do NOT translate any word or phrase" in system_message
    assert "komanse -> kòmanse" in system_message
    assert "kek -> kèk" in system_message
    assert "Do NOT paraphrase" in system_message


def test_ht_review_non_json_output_requires_human_review():
    chunk = _extract_chunk_payload(
        "SPEAKER_00 (00:00:00)\nCorrected text, but not JSON.",
        "raw text",
        0,
    )

    assert chunk.corrected_text == "SPEAKER_00 (00:00:00)\nCorrected text, but not JSON."
    assert chunk.needs_human_review is True
    assert chunk.parse_error is True
    assert "non-JSON" in chunk.notes


def test_ht_review_postprocess_repairs_observed_safe_terms():
    reviewed = "So, an kek mo. Trè byen, pou jè Saint-Anne lan."

    cleaned = _postprocess_review_text(
        reviewed,
        ["Projet Saint-Anne", "Project Saint-Anne"],
    )

    assert "an kèk mo" in cleaned
    assert "Projet Saint-Anne lan" in cleaned
    assert "pou jè Saint-Anne" not in cleaned
