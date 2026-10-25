"""Train the spaCy NER model from the annotated call transcripts.

Usage::

    python -m apps.callers.nlp.train_ner
    python -m apps.callers.nlp.train_ner --epochs 40
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_ANNOTATIONS = DATA_DIR / "annotations.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "models" / "ner"

LABELS = ("NAME", "AGE", "GENDER", "CIVIL_STATUS", "LOCATION")


def load_annotations(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("annotations") or data.get("data") or []
    if not isinstance(data, list):
        raise ValueError("annotations.json must contain a list of records")
    return [record for record in data if isinstance(record, dict) and record.get("text")]


def _resolve_span(text: str, entity: dict) -> tuple[int, int] | None:
    entity_text = str(entity.get("text") or "").strip()
    start = entity.get("start")
    end = entity.get("end")

    if isinstance(start, int) and isinstance(end, int):
        if 0 <= start < end <= len(text) and text[start:end] == entity_text:
            return start, end

    if entity_text:
        found = text.find(entity_text)
        if found != -1:
            return found, found + len(entity_text)
    return None


def build_examples(nlp, records: list[dict]) -> tuple[list, int]:
    from spacy.training import Example

    examples = []
    skipped = 0
    for record in records:
        text = str(record.get("text") or "")
        reference = nlp.make_doc(text)
        spans = []
        for entity in record.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            label = str(entity.get("label") or "").upper()
            if label not in LABELS:
                continue
            resolved = _resolve_span(text, entity)
            if resolved is None:
                skipped += 1
                continue
            start, end = resolved
            span = reference.char_span(start, end, label=label, alignment_mode="expand")
            if span is None:
                skipped += 1
                continue
            spans.append(span)
        if not spans:
            skipped += 1
            continue

        spans.sort(key=lambda span: (span.start_char, -(span.end_char - span.start_char)))
        kept = []
        for span in spans:
            overlaps = any(
                span.start_char < other.end_char and span.end_char > other.start_char
                for other in kept
            )
            if overlaps:
                skipped += 1
                continue
            kept.append(span)

        if not kept:
            skipped += 1
            continue
        reference.set_ents(kept)
        examples.append(Example(nlp.make_doc(text), reference))
    return examples, skipped


def train(annotations: Path, output: Path, epochs: int = 30, seed: int = 13) -> dict:
    import spacy
    from spacy.util import compounding, minibatch

    if not annotations.exists():
        raise FileNotFoundError(
            f"Annotation file not found: {annotations}\n"
            "Save the annotated corpus there before training."
        )

    records = load_annotations(annotations)
    if not records:
        raise ValueError("No annotated records found.")

    nlp = spacy.blank("en")
    nlp.add_pipe("tok2vec")
    ner = nlp.add_pipe("ner")
    for label in LABELS:
        ner.add_label(label)

    examples, skipped = build_examples(nlp, records)
    if not examples:
        raise ValueError("No usable annotated entities were found.")

    random.seed(seed)
    random.shuffle(examples)
    split = max(1, int(len(examples) * 0.8))
    train_examples = examples[:split]
    dev_examples = examples[split:] or examples[:split]

    optimizer = nlp.initialize(lambda: train_examples)
    metrics = {}
    best_metrics = {}
    best_bytes = None
    best_f = -1.0
    for epoch in range(1, epochs + 1):
        random.shuffle(train_examples)
        losses = {}
        batches = minibatch(train_examples, size=compounding(4.0, 32.0, 1.001))
        for batch in batches:
            nlp.update(batch, sgd=optimizer, losses=losses)
        scores = nlp.evaluate(dev_examples)
        metrics = {
            "epoch": epoch,
            "loss": round(float(losses.get("ner", 0.0)), 4),
            "ents_f": round(float(scores.get("ents_f", 0.0)), 4),
            "ents_p": round(float(scores.get("ents_p", 0.0)), 4),
            "ents_r": round(float(scores.get("ents_r", 0.0)), 4),
        }
        if metrics["ents_f"] >= best_f:
            best_f = metrics["ents_f"]
            best_metrics = metrics
            best_bytes = nlp.to_bytes()
        print(
            f"epoch {epoch:03d}  loss={metrics['loss']:.4f}  "
            f"P={metrics['ents_p']:.3f}  R={metrics['ents_r']:.3f}  F={metrics['ents_f']:.3f}"
        )

    if best_bytes is not None:
        nlp.from_bytes(best_bytes)

    output.mkdir(parents=True, exist_ok=True)
    nlp.to_disk(output)
    summary = {
        "records": len(records),
        "examples": len(examples),
        "skipped": skipped,
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
    parser = argparse.ArgumentParser(description="Train the Sentimental NER model.")
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=30)
    args = parser.parse_args(argv)

    try:
        train(args.annotations, args.output, epochs=args.epochs)
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
