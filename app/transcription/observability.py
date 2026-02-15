# app/transcription/observability.py
from __future__ import annotations

from collections import Counter
from typing import Dict, List


class PipelineMetrics:
    def __init__(self):
        self.rules = {}
        self.layers = {}

    def bump(self, layer: str):
        """
        Increment a pipeline layer counter.
        Used only for observability.
        """
        self.layers[layer] = self.layers.get(layer, 0) + 1

    def bump_rule(self, rule: str):
        """
        Optional: track individual rule firings later
        """
        self.rules[rule] = self.rules.get(rule, 0) + 1

    def snapshot(self):
        return {
            "rules": self.rules,
            "layers": self.layers,
        }
