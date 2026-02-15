import pytest
from app.transcription.reversal import A3Event, detect_a3_reversals

def test_detects_simple_reversal():
    events = [
        A3Event(rule_id="A3.un_pale", before="un pale", after="ann pale", mode="restricted"),
    ]
    final_text = "mwen di: un pale sou sa."  # after disappeared, before returned
    rev = detect_a3_reversals(a3_events=events, final_text=final_text)
    assert len(rev) == 1
    assert rev[0].rule_id == "A3.un_pale"

def test_no_reversal_when_after_present():
    events = [
        A3Event(rule_id="A3.un_pale", before="un pale", after="ann pale", mode="restricted"),
    ]
    final_text = "ann pale sou sa."
    rev = detect_a3_reversals(a3_events=events, final_text=final_text)
    assert rev == []
