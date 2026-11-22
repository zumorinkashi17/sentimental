"""Optional locally trained text-classifier support for suicide risk flags.

Training is done with ``python -m apps.callers.nlp.train_risk``. The trained
model is loaded lazily, with graceful fallback to the rule engine. Adding more
annotated examples to ``data/suicide_risk_annotations.json`` and retraining is
the supported way to teach the flagger new terminology.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "models" / "risk"


@lru_cache(maxsize=1)
def get_risk_nlp():
    if not (MODEL_DIR / "config.cfg").exists():
        return None
    try:
        spacy = import_module("spacy")
        return spacy.load(str(MODEL_DIR))
    except Exception:
        return None


def is_available() -> bool:
    return get_risk_nlp() is not None


def predict(text: str) -> dict | None:
    """Return predicted label/confidence or ``None`` when unavailable."""
    nlp = get_risk_nlp()
    if nlp is None:
        return None
    from .risk import normalize_text

    doc = nlp(normalize_text(text))
    if not doc.cats:
        return None
    label = max(doc.cats, key=doc.cats.get)
    return {"label": label, "confidence": float(doc.cats[label])}
