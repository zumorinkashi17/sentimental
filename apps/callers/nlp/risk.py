"""C-SSRS-based suicide risk flagging for Cebuano, Taglish and English text.

Rules live in ``data/suicide_risk_rules.json`` so counselors can tune phrases
and severity weights without changing code. A locally trained spaCy text
classifier can be added later via ``train_risk.py``; the rule engine always
runs as the safety fallback.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import risk_model

RULES_PATH = Path(__file__).resolve().parent / "data" / "suicide_risk_rules.json"

TIER_ORDER = {"LOW": 0, "MODERATE_RISK": 1, "HIGH_RISK": 2}

_CALLER_LABEL = re.compile(
    r"^\s*(?:\[\s*(?:caller|callers)\s*\]|(?:caller|callers)\s*[:：-])\s*",
    re.IGNORECASE,
)
_RESPONDER_LABEL = re.compile(
    r"^\s*(?:\[\s*(?:counselor|counsellor|responder|therapist|agent)\s*\]"
    r"|(?:counselor|counsellor|responder|therapist|agent)\s*[:：-])\s*",
    re.IGNORECASE,
)


def _caller_speech(text: object) -> str:
    raw = str(text or "")
    if not raw:
        return raw
    kept = []
    saw_label = False
    speaker = None
    for line in raw.splitlines():
        responder_match = _RESPONDER_LABEL.match(line)
        if responder_match:
            saw_label = True
            speaker = "responder"
            continue
        caller_match = _CALLER_LABEL.match(line)
        if caller_match:
            saw_label = True
            speaker = "caller"
            remainder = line[caller_match.end():]
            if remainder.strip():
                kept.append(remainder)
            continue
        if speaker != "responder":
            kept.append(line)
    return "\n".join(kept) if saw_label else raw


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> dict:
    target = Path(path) if path else RULES_PATH
    with target.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def _collapse_repeats(token: str, limit: int) -> str:
    return re.sub(r"(.)\1{%d,}" % max(1, limit - 1), r"\1" * limit, token)


def normalize_text(text: object, rules: dict | None = None) -> str:
    """Lowercase, collapse repeated characters and extra whitespace.

    Spelling variants are handled at match time (see ``_phrase_pattern``)
    rather than by rewriting words, which keeps each configured phrase intact.
    """
    rules = rules or load_rules()
    value = str(text or "").lower().replace("’", "'")
    limit = int(rules.get("normalization", {}).get("repeated_char_max", 2))
    value = " ".join(_collapse_repeats(token, limit) for token in value.split())
    value = re.sub(r"\s*-\s*", " ", value)
    return re.sub(r"\s+", " ", value).strip()


class SuicideRiskEvaluator:
    """Evaluate text and return a structured C-SSRS risk result."""

    def __init__(self, rules_path: str | None = None):
        self.rules = load_rules(rules_path)
        self.settings = self.rules.get("settings", {})
        self.negation_window = int(self.settings.get("negation_window", 6))
        self.weights = self.settings.get("severity_weights", {})
        self.negations = set(self.rules.get("negations", []))
        self.idioms = list(self.rules.get("idioms", []))
        self._variants: dict[str, set[str]] = {}
        for group in self.rules.get("normalization", {}).get("variants", []):
            if isinstance(group, list):
                words = {str(word).lower().strip() for word in group if str(word).strip()}
                for word in words:
                    self._variants.setdefault(word, set()).update(words)
        self._idiom_patterns = [(idiom, self._phrase_pattern(idiom)) for idiom in self.idioms]
        clear_denials = [
            str(phrase)
            for phrase in self.rules.get("clear_denials", [])
            if str(phrase).strip()
        ]
        self._clear_denial_patterns = [
            (phrase, self._phrase_pattern(phrase)) for phrase in clear_denials
        ]
        self._patterns = {
            tier: {
                item["category"]: [
                    (phrase, self._phrase_pattern(phrase))
                    for phrase in item.get("phrases", [])
                ]
                for item in items
            }
            for tier, items in self.rules.get("tiers", {}).items()
        }

    def _phrase_pattern(self, phrase: str) -> re.Pattern:
        alternatives = []
        parts = phrase.split()
        for part in parts:
            forms = self._variants.get(part, {part})
            alternatives.append("(?:" + "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)) + ")")
        body = r"\s+".join(alternatives)
        return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")

    def evaluate(self, text: object) -> dict:
        normalized = normalize_text(_caller_speech(text), self.rules)
        tokens = normalized.split()

        idiom_hits = [idiom for idiom, pattern in self._idiom_patterns if pattern.search(normalized)]
        hits: dict[str, dict[str, list[str]]] = {}
        for tier in ("HIGH_RISK", "MODERATE_RISK"):
            for category, patterns in self._patterns.get(tier, {}).items():
                for phrase, pattern in patterns:
                    for match in pattern.finditer(normalized):
                        start_token = len(normalized[: match.start()].split())
                        before = tokens[max(0, start_token - self.negation_window) : start_token]
                        if any(token in self.negations for token in before):
                            hits.setdefault("LOW", {}).setdefault(
                                "Negated Risk Language", []
                            ).append(match.group(0))
                        else:
                            hits.setdefault(tier, {}).setdefault(category, []).append(match.group(0))

        # A generic "suicide" keyword alone is HIGH, but when it is part of a
        # clearly non-specific ideation phrase (Level 2) keep it MODERATE.
        high_categories = hits.get("HIGH_RISK", {})
        if "Ideation Level 3 - Method" in high_categories:
            method_phrases = set(high_categories["Ideation Level 3 - Method"])
            if method_phrases <= {"suicide", "suicidality", "self harm", "self harming", "self injury"} and "MODERATE_RISK" in hits:
                del hits["HIGH_RISK"]

        if idiom_hits and not any(
            tier in hits for tier in ("HIGH_RISK", "MODERATE_RISK")
        ):
            return {
                "risk_level": "LOW",
                "cssrs_category": "Non-Literal Idiom / False Positive",
                "matched_phrases": idiom_hits,
                "flag_reason": "Matched known non-literal idiom(s): " + ", ".join(idiom_hits[:5]) + ".",
                "score": 0,
                "normalized_text": normalized,
            }

        denial_hits = [
            phrase
            for phrase, pattern in self._clear_denial_patterns
            if pattern.search(normalized)
        ]
        denial_hits = [
            phrase
            for phrase in denial_hits
            if not any(other != phrase and phrase in other for other in denial_hits)
        ]
        if denial_hits and not any(
            tier in hits for tier in ("HIGH_RISK", "MODERATE_RISK")
        ):
            return {
                "risk_level": "LOW",
                "cssrs_category": "Explicit Denial of Suicidal Ideation",
                "matched_phrases": denial_hits,
                "flag_reason": "Caller explicitly denied suicidal thoughts: "
                + ", ".join(denial_hits[:5])
                + ".",
                "score": 0,
                "normalized_text": normalized,
            }

        risk_level = "LOW"
        cssrs_category = "No Risk Indicators"
        flag_reason = "No risk indicators matched."
        matched: list[str] = []
        score = 0
        if hits:
            risk_level = max(hits, key=lambda tier: TIER_ORDER.get(tier, 0))
            categories = hits[risk_level]
            cssrs_category = "; ".join(categories)
            seen: set[str] = set()
            for phrases in categories.values():
                for phrase in phrases:
                    if phrase not in seen:
                        seen.add(phrase)
                        matched.append(phrase)
            score = int(self.weights.get(risk_level, 0))
            if risk_level == "HIGH_RISK":
                flag_reason = (
                    f"Matched {cssrs_category}: {', '.join(matched[:5])}. "
                    "Immediate Responder review required."
                )
            elif risk_level == "MODERATE_RISK":
                flag_reason = (
                    f"Matched {cssrs_category}: {', '.join(matched[:5])}. "
                    "Responder follow-up recommended."
                )
            else:
                flag_reason = (
                    f"Negated risk language detected: {', '.join(matched[:5])}. "
                    "No active risk indicator."
                )

        prediction = risk_model.predict(normalized)
        threshold = float(self.settings.get("trained_model_threshold", 0.65))
        if prediction and prediction["confidence"] >= threshold:
            predicted_level = prediction["label"]
            if TIER_ORDER.get(predicted_level, 0) > TIER_ORDER.get(risk_level, 0):
                risk_level = predicted_level
                cssrs_category = "Model Prediction: " + cssrs_category
                flag_reason += (
                    f" Trained model predicted {predicted_level} "
                    f"({prediction['confidence']:.0%} confidence)."
                )
                score = int(self.weights.get(risk_level, 0))

        return {
            "risk_level": risk_level,
            "cssrs_category": cssrs_category,
            "matched_phrases": matched,
            "flag_reason": flag_reason,
            "score": score,
            "normalized_text": normalized,
        }


_evaluator = SuicideRiskEvaluator()


def evaluate_suicide_risk(text: object) -> dict:
    """Public helper used by the NLP pipeline and the save endpoint."""
    return _evaluator.evaluate(text)
