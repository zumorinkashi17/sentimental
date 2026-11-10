"""Hybrid information-extraction pipeline used by the documentation panel."""

from __future__ import annotations

import re

from . import ner
from .intervention import extract_intervention
from .rules import (
    canonical_civil_status,
    canonical_gender,
    canonical_location,
    clean_text,
    extract_caller_text,
    extract_responder_text,
    extract_rules,
    infer_civil_status_from_context,
    infer_gender_from_context,
    is_known_location,
    is_name_candidate,
    is_workplace_location,
    parse_age,
    requests_anonymity,
)
from .summary import build_summary, translate_summary
from .textrank import summarize

FIELD_LABELS = {
    "callerName": "NAME",
    "callerAge": "AGE",
    "callerGender": "GENDER",
    "callerStatus": "CIVIL_STATUS",
    "callerLocation": "LOCATION",
}


def _merge_entities(rule_entities: list[dict], ner_entities: list[dict]) -> list[dict]:
    """Combine both sources, keeping the strongest entity per span/label."""
    merged: list[dict] = []
    for entity in [*rule_entities, *ner_entities]:
        duplicate = next(
            (
                other
                for other in merged
                if other["label"] == entity["label"]
                and other["start"] == entity["start"]
                and other["end"] == entity["end"]
            ),
            None,
        )
        if duplicate is None:
            merged.append(entity)
        elif entity["confidence"] > duplicate["confidence"]:
            merged[merged.index(duplicate)] = entity
    merged.sort(key=lambda item: (item["start"], item["label"]))
    return merged


_LOCATION_CUE = re.compile(
    r"\b(?:sa|taga|diri|dinhi|didto|diha|dapit|near|located|live)\s+"
    r"(?:(?:sa|may|dapit|near|ang|among|akong|si)\s+){0,2}$",
    re.IGNORECASE,
)

_PLACE_SUFFIX = re.compile(
    r"\b(?:city|municipality|province|barangay|brgy|sitio|purok|subdivision|"
    r"street|st|avenue|ave|road|rd|drive|village|district|town)\b",
    re.IGNORECASE,
)

_NER_NAME_CUE = re.compile(
    r"\b(?:ako(?:ng)?\s+si|ako\s+diay\s+si|si\s+\w+\s+ko|"
    r"akong\s+(?:ngalan|name|pangalan)|ang\s+(?:ngalan|name|pangalan)|"
    r"tawga|tawag|call\s+me|my\s+name|i'?m)\b",
    re.IGNORECASE,
)


def _valid_ner_entity(entity: dict, text: str) -> bool:
    """Reject NER guesses that contradict the closed-vocabulary lexicons."""
    label = entity["label"]
    value = entity["text"]

    if label == "GENDER":
        return canonical_gender(value) is not None
    if label == "CIVIL_STATUS":
        return canonical_civil_status(value) is not None
    if label == "AGE":
        return parse_age(value) is not None
    if label == "NAME":
        if requests_anonymity(text):
            return False
        if not is_name_candidate(value):
            return False
        context = text[
            max(0, entity["start"] - 40) : min(len(text), entity["end"] + 20)
        ]
        return bool(_NER_NAME_CUE.search(context))
    if label == "LOCATION":
        if is_workplace_location(text, entity["start"], entity["end"]):
            return False
        before = text[max(0, entity["start"] - 30) : entity["start"]]
        has_cue = bool(_LOCATION_CUE.search(before))
        if _PLACE_SUFFIX.search(value):
            return has_cue or is_known_location(value)
        if is_known_location(value):
            return has_cue
        return False
    return False


def _best(entities: list[dict], label: str) -> dict | None:
    candidates = [entity for entity in entities if entity["label"] == label]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item["confidence"], item["start"]))
    return candidates[0]


def _field_value(field: str, entity: dict):
    if field == "callerAge":
        if isinstance(entity.get("value"), int):
            return entity["value"]
        return parse_age(entity["text"])
    if field == "callerGender":
        if entity["source"] == "rule" and entity.get("value"):
            return entity["value"]
        return canonical_gender(entity["text"]) or entity["text"]
    if field == "callerStatus":
        if entity["source"] == "rule" and entity.get("value"):
            return entity["value"]
        return canonical_civil_status(entity["text"]) or entity["text"]
    if field == "callerLocation":
        if entity["source"] == "rule" and entity.get("value"):
            return entity["value"]
        return canonical_location(entity["text"])
    return entity.get("value") or entity["text"]


def analyze(
    text: str,
    max_summary_sentences: int = 4,
    *,
    reason_for_calling: object = "",
    risk_assessment: object = "",
) -> dict:
    """Extract caller fields and generate a TextRank-driven English summary.

    The Bisaya template is still built by ``build_summary`` and returned as
    ``summary_bisaya`` for reference. Returns a JSON-serialisable payload
    consumed by the persistent panel.
    """
    cleaned = clean_text(text)
    caller_text = extract_caller_text(text)
    responder_text = extract_responder_text(text)
    rule_entities = extract_rules(caller_text)
    ner_entities = [
        entity
        for entity in ner.extract_ner(caller_text)
        if _valid_ner_entity(entity, caller_text)
    ]
    entities = _merge_entities(rule_entities, ner_entities)

    fields: dict[str, object] = {}
    field_meta: dict[str, dict] = {}
    for field, label in FIELD_LABELS.items():
        best = _best(entities, label)
        if best is None:
            fields[field] = "N/A"
            field_meta[field] = {"confidence": 0.0, "source": None, "evidence": ""}
            continue
        fields[field] = _field_value(field, best) or "N/A"
        field_meta[field] = {
            "confidence": best["confidence"],
            "source": best["source"],
            "evidence": best["text"],
            "start": best["start"],
            "end": best["end"],
        }

    if fields.get("callerGender") == "N/A":
        inferred_gender = infer_gender_from_context(caller_text)
        if inferred_gender:
            fields["callerGender"] = inferred_gender
            field_meta["callerGender"] = {
                "confidence": 0.6,
                "source": "inference",
                "evidence": "spouse reference",
            }

    if fields.get("callerStatus") == "N/A":
        inferred_status = infer_civil_status_from_context(caller_text)
        if inferred_status:
            fields["callerStatus"] = inferred_status
            field_meta["callerStatus"] = {
                "confidence": 0.6,
                "source": "inference",
                "evidence": "spouse reference",
            }

    intervention, intervention_categories = extract_intervention(
        caller_text, responder_text
    )
    fields["intervention"] = intervention or "N/A"
    field_meta["intervention"] = {
        "confidence": 0.8 if intervention else 0.0,
        "source": "dictionary" if intervention else None,
        "evidence": intervention,
        "categories": intervention_categories,
    }

    textrank_summary = summarize(
        caller_text,
        max_sentences=max_summary_sentences,
        min_words=2,
    )
    summary_bisaya = build_summary(
        caller_text,
        summary_text=textrank_summary,
        reason_for_calling=reason_for_calling,
        risk_assessment=risk_assessment,
        intervention_categories=intervention_categories,
        max_symptoms=max_summary_sentences,
    )
    summary = translate_summary(summary_bisaya)

    return {
        "status": "success",
        "fields": fields,
        "field_meta": field_meta,
        "entities": entities,
        "summary": summary,
        "summary_bisaya": summary_bisaya,
        "summary_method": "textrank+template",
        "summary_extract": textrank_summary,
        "method": "hybrid" if ner.is_available() else "rules",
        "text_length": len(cleaned),
    }
