# tests/test_a3_promotion_log.py
import os
import pytest
from pathlib import Path

from app.transcription.promotion import A3_LOG_PATH


@pytest.mark.integration
def test_a3_log_path_exists_after_runs():
    # We don't force A3 to happen, we only ensure path location is valid
    assert A3_LOG_PATH.parent.exists()
    # A3_LOG_PATH may or may not exist depending on whether A3 fired
