from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Rule:
    match: str
    value: str
    classification: str


@dataclass(slots=True)
class CorpusRules:
    default_classification: str
    rules: list[Rule]

    def classify_model(self, model_name: str) -> str:
        return self.classify(model_name, "")

    def classify(self, model_name: str, relative_path: str) -> str:
        normalized_path = relative_path.replace("/", "\\").lower()
        for rule in self.rules:
            if rule.match == "model_exact" and model_name == rule.value:
                return rule.classification
            if rule.match == "model_prefix" and model_name.startswith(rule.value):
                return rule.classification
            if rule.match == "path_contains" and rule.value.lower() in normalized_path:
                return rule.classification
        return self.default_classification


def load_rules(path: str | Path) -> CorpusRules:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = [Rule(**item) for item in payload.get("rules", [])]
    return CorpusRules(
        default_classification=payload.get("default_classification", "custom-canonical"),
        rules=rules,
    )

