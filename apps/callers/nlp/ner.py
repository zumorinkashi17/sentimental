"""Trained spaCy NER half of the hybrid extractor."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent / "models" / "ner"
SUPPORTED_LABELS = ("NAME", "AGE", "GENDER", "CIVIL_STATUS", "LOCATION")


@lru_cache(maxsize=1)
def get_nlp():
    """Load the trained model once per process, or return ``None``."""
    if not MODEL_DIR.exists():
        logger.info("NER model not found at %s; using rule-based extraction only.", MODEL_DIR)
        return None
    try:
        import spacy

        return spacy.load(MODEL_DIR)
    except Exception as exc:  # pragma: no cover - depends on local model files
        logger.warning("Could not load the NER model (%s); falling back to rules.", exc)
        return None


def is_available() -> bool:
    return get_nlp() is not None


def extract_ner(text: str) -> list[dict]:
    """Return entities predicted by the trained model."""
    nlp = get_nlp()
    if nlp is None or not text:
        return []

    try:
        doc = nlp(text)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("NER inference failed: %s", exc)
        return []

    entities = []
    for entity in doc.ents:
        label = entity.label_.upper()
        if label not in SUPPORTED_LABELS:
            continue
        entities.append(
            {
                "label": label,
                "text": entity.text,
                "start": entity.start_char,
                "end": entity.end_char,
                "value": entity.text,
                "confidence": 0.82,
                "source": "ner",
            }
        )
    return entities
