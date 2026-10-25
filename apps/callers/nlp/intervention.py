"""Classify a call into the intervention categories from ``dictionary.json``.

The documentation panel stores intervention as the category label(s) used by
the call centre, not a free-form quote. A call can need more than one label
(for example psychoeducation plus a referral), so this is multi-label.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DICTIONARY_PATH = Path(__file__).resolve().parent / "data" / "dictionary.json"
_WORD_RE = re.compile(r"[^a-z0-9À-ÿ]+")

_SUPPORT_CATEGORY = "Responder provided empathetic listening and support"

_CATEGORY_ORDER = (
    "Referred to Emergency Room",
    "Referred to Guidance Counselors",
    "Given Referrals",
    "Refused Referrals",
    "Psychoeducation",
    "Others",
    _SUPPORT_CATEGORY,
)

# Specific, actionable categories are always kept when they have evidence.
_SPECIFIC_CATEGORIES = {
    "Referred to Emergency Room",
    "Referred to Guidance Counselors",
    "Refused Referrals",
}

_MIN_GENERAL_SCORE = 4.0
_GENERAL_RELATIVE_SCORE = 0.4

# Weights are derived from the vocabulary used by the matching category in
# dictionary.json. A single strong cue is enough to select a category.
_RULES: dict[str, dict[str, float]] = {
    "Referred to Emergency Room": {
        "emergency room": 3,
        "emergency department": 3,
        "emergency services": 3,
        "emergency evaluation": 3,
        "emergency response": 3,
        "medical emergency": 3,
        "psychiatric emergency": 3,
        "urgent care": 2,
        "911": 3,
        "rescue": 2,
        "er": 2,
    },
    "Referred to Guidance Counselors": {
        "guidance counselor": 3,
        "guidance office": 3,
        "school counselor": 2,
        "academic adviser": 2,
        "student affairs": 2,
    },
    "Given Referrals": {
        "refer": 2,
        "referred": 2,
        "referral": 2,
        "consult": 2,
        "doctor": 2,
        "doktor": 2,
        "psychiatrist": 3,
        "psychologist": 3,
        "counselor": 2,
        "mental health professional": 3,
        "treatment": 2,
        "rehabilitation": 3,
        "rehab": 2,
        "center": 2,
        "out patient": 3,
        "program": 1,
        "detox": 2,
        "medical": 2,
        "hospital": 2,
        "clinic": 2,
        "health center": 2,
        "rhu": 2,
        "doh": 3,
        "contact details": 2,
        "wellness institute": 2,
        "medical arts": 2,
        "life coach": 2,
        "career counselor": 2,
    },
    "Refused Referrals": {
        "dili lang sa": 3,
        "di lang sa": 3,
        "dili pa ko ready": 3,
        "di pa ko ready": 3,
        "dili pa nako": 2,
        "di pa nako": 2,
        "wala pa koy budget": 3,
        "wala koy budget": 3,
        "dili usa nang": 3,
        "di usa nang": 3,
        "dili lang siguro": 2,
        "di lang siguro": 2,
        "basin di pa": 2,
        "di pa sure": 2,
        "dili pa sure": 2,
        "ayaw sa": 2,
    },
    "Psychoeducation": {
        "withdrawal": 3,
        "severe withdrawal": 3,
        "symptom": 2,
        "symptoms": 2,
        "anxiety": 2,
        "depress": 2,
        "stress": 2,
        "trauma": 2,
        "alcohol": 2,
        "bisyo": 2,
        "addiction": 2,
        "depende": 2,
        "dependence": 2,
        "relapse": 2,
        "trigger": 2,
        "medication": 2,
        "tambal": 2,
        "dosage": 2,
        "mental health": 2,
        "coping mechanism": 2,
        "kondisyon": 2,
        "diagnosis": 2,
        "assessment": 2,
        "psychoeducation": 3,
        "psychology": 3,
        "mid twenties crisis": 3,
        "mid-twenties crisis": 3,
        "natural nga phase": 2,
        "social media": 2,
        "best moments": 2,
        "timeline": 2,
        "compare": 2,
        "itandi": 2,
        "empty nest": 3,
        "empty nest syndrome": 3,
        "grief": 2,
        "grieving": 2,
        "side effect": 2,
        "insomnia": 2,
        "sleep problem": 2,
        "eap": 2,
        "employee assistance": 2,
        "relationship counseling": 2,
        "couples counseling": 2,
        "health services": 2,
    },
    "Others": {
        "barangay": 2,
        "dswd": 3,
        "blotter": 3,
        "vawc": 3,
        "wcpc": 3,
        "police": 2,
        "nbi": 3,
        "cybercrime": 3,
        "social services": 3,
        "city hall": 2,
        "church": 2,
        "simbahan": 2,
        "kapilya": 2,
        "lupon": 2,
        "mediation": 2,
        "legal": 2,
        "aics": 3,
        "senior citizens": 2,
        "legion of mary": 2,
        "women s and children s protection": 2,
    },
    "Responder provided empathetic listening and support": {
        "listen": 2,
        "listening": 2,
        "maminaw": 2,
        "validate": 2,
        "validation": 2,
        "support": 2,
        "proud": 2,
        "nalipay": 2,
        "courage": 2,
        "kaisog": 2,
        "kaya": 1,
        "andam": 2,
        "safe": 2,
        "nakasabot": 2,
        "sabot": 2,
        "empathy": 2,
        "inhale": 2,
        "exhale": 2,
        "ginhawa": 2,
        "breathing": 2,
        "focus": 1,
        "ground": 2,
        "coping": 2,
        "self care": 2,
        "tubig": 2,
        "water": 2,
        "rest": 1,
        "pahulay": 2,
        "sleep": 1,
        "tulog": 2,
        "eat": 1,
        "kaon": 1,
        "walk": 1,
        "lakaw": 1,
        "exercise": 2,
        "journal": 2,
        "isulat": 2,
        "write": 1,
        "list": 1,
        "plano": 1,
        "plan": 1,
    },
}


def _normalize(text: str) -> str:
    normalized = _WORD_RE.sub(" ", str(text or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _score(text: str, rules: dict[str, float]) -> float:
    normalized = _normalize(text)
    if not normalized:
        return 0.0
    tokens = set(normalized.split())
    padded = f" {normalized} "
    score = 0.0
    for keyword, weight in rules.items():
        phrase = _normalize(keyword)
        if not phrase:
            continue
        if " " in phrase:
            if f" {phrase} " in padded:
                score += weight
        elif phrase in tokens:
            score += weight
    return score


@lru_cache(maxsize=1)
def _load_phrases() -> dict[str, tuple[str, ...]]:
    try:
        with _DICTIONARY_PATH.open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
        raw = data.get("intervention", {}).get("categories", {})
        return {
            category: tuple(
                phrase
                for phrase in (_normalize(item) for item in items)
                if len(phrase.split()) >= 2 and len(phrase) >= 8
            )
            for category, items in raw.items()
        }
    except (OSError, json.JSONDecodeError):
        return {category: () for category in _CATEGORY_ORDER}


def _matches_dictionary_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    padded = f" {normalized} "
    return any(f" {phrase} " in padded for phrase in phrases)


def extract_intervention(
    caller_text: str, responder_text: str
) -> tuple[str, list[str]]:
    """Return one or more intervention labels that the call clearly supports."""
    phrases = _load_phrases()
    specific: list[tuple[int, str, float]] = []
    general: list[tuple[int, str, float]] = []
    support_match = False
    specific_referral = False

    for order, category in enumerate(_CATEGORY_ORDER):
        if category not in phrases:
            continue
        source = caller_text if category == "Refused Referrals" else responder_text
        score = _score(source, _RULES[category])
        if _matches_dictionary_phrase(source, phrases[category]):
            score = max(score, 4.0)
        if (
            category == "Given Referrals"
            and specific_referral
            and score <= 2.0
        ):
            continue
        if score < 2.0:
            continue

        if category == _SUPPORT_CATEGORY:
            support_match = True
            continue

        item = (order, category, score)
        if category in _SPECIFIC_CATEGORIES:
            specific.append(item)
            if category in (
                "Referred to Emergency Room",
                "Referred to Guidance Counselors",
            ):
                specific_referral = True
        else:
            general.append(item)

    selected = list(specific)
    if general:
        top_general = max(score for _, _, score in general)
        threshold = max(_MIN_GENERAL_SCORE, top_general * _GENERAL_RELATIVE_SCORE)
        strong = [item for item in general if item[2] >= threshold]
        if not specific and not strong:
            strong = [max(general, key=lambda item: (item[2], -item[0]))]
        selected.extend(strong)

    if not selected:
        if support_match:
            return _SUPPORT_CATEGORY, [_SUPPORT_CATEGORY]
        return "N/A", []

    selected.sort(key=lambda item: item[0])
    labels = [category for _, category, _ in selected]
    return "\n".join(f"- {label}" for label in labels), labels
