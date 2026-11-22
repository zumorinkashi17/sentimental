"""Train the optional C-SSRS suicide-risk text classifier.

The rule engine in ``risk.py`` remains the authoritative safety net. This
command trains a spaCy textcat model from counselor-corrected labels so the
flagger can recognise new phrasings. Training data lives in
``data/suicide_risk_annotations.json``::

    {"text": "...", "label": "HIGH_RISK", "category": "..."}

Usage::

    python -m apps.callers.nlp.train_risk
    python -m apps.callers.nlp.train_risk --epochs 40 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .risk import TIER_ORDER, normalize_text

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_ANNOTATIONS = DATA_DIR / "suicide_risk_annotations.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "models" / "risk"
LABELS = ("LOW", "MODERATE_RISK", "HIGH_RISK")


def load_annotations(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("annotations") or data.get("data") or []
    if not isinstance(data, list):
        raise ValueError("suicide_risk_annotations.json must contain a list")
    records = []
    for record in data:
        if not isinstance(record, dict):
            continue
        text = str(record.get("text") or "").strip()
        label = str(record.get("label") or "").strip().upper()
        if text and label in LABELS:
            records.append({"text": text, "label": label, "category": record.get("category", "")})
    return records


def build_examples(nlp, records: list[dict]):
    from spacy.training import Example

    examples = []
    for record in records:
        doc = nlp.make_doc(normalize_text(record["text"]))
        cats = {label: 0.0 for label in LABELS}
        cats[record["label"]] = 1.0
        examples.append(Example.from_dict(doc, {"cats": cats}))
    return examples


def train(annotations: Path, output: Path, epochs: int = 30, seed: int = 13) -> dict:
    import spacy
    from spacy.util import compounding, minibatch

    if not annotations.exists():
        raise FileNotFoundError(f"Annotation file not found: {annotations}")
    records = load_annotations(annotations)
    if not records:
        raise ValueError("No annotated records found.")

    nlp = spacy.blank("en")
    nlp.add_pipe("tok2vec")
    textcat = nlp.add_pipe("textcat")
    for label in LABELS:
        textcat.add_label(label)

    examples = build_examples(nlp, records)
    random.seed(seed)
    random.shuffle(examples)
    split = max(1, int(len(examples) * 0.8))
    train_examples = examples[:split]
    dev_examples = examples[split:] or examples[:split]

    optimizer = nlp.initialize(lambda: train_examples)
    metrics = {}
    best_metrics = {}
    best_bytes = None
    best_score = -1.0
    for epoch in range(1, epochs + 1):
        random.shuffle(train_examples)
        losses = {}
        for batch in minibatch(train_examples, size=compounding(4.0, 32.0, 1.001)):
            nlp.update(batch, sgd=optimizer, losses=losses)
        scores = nlp.evaluate(dev_examples)
        accuracy = float(scores.get("cats_macro_auc", 0.0))
        f1 = float(scores.get("cats_micro_f", 0.0))
        metrics = {
            "epoch": epoch,
            "loss": round(float(losses.get("textcat", 0.0)), 4),
            "accuracy": round(accuracy, 4),
            "f1": round(f1, 4),
        }
        if accuracy >= best_score:
            best_score = accuracy
            best_metrics = metrics
            best_bytes = nlp.to_bytes()
        print(
            f"epoch {epoch:03d}  loss={metrics['loss']:.4f}  "
            f"auc={accuracy:.3f}  f={f1:.3f}"
        )

    if best_bytes is not None:
        nlp.from_bytes(best_bytes)
    output.mkdir(parents=True, exist_ok=True)
    nlp.to_disk(output)
    summary = {
        "records": len(records),
        "examples": len(examples),
        "epochs": epochs,
        "labels": list(LABELS),
        "best_metrics": best_metrics,
        "final_metrics": metrics,
    }
    (output / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved model to {output}")
    print(json.dumps(summary, indent=2))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Train the SentiMental suicide-risk classifier.")
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args(argv)
    try:
        train(args.annotations, args.output, epochs=args.epochs, seed=args.seed)
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
