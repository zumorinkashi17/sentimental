"""Identify the predicted busiest recorded shift per forecast month.

Two shifts are only considered *distinguishable* when their 80% prediction
intervals do not overlap **and** the relative gap between their point forecasts
exceeds a small threshold. Otherwise the month is flagged ``uncertain`` so that
downstream UI never presents a close call as a confident result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .constants import SERIES_LABELS, SHIFT_SERIES
from .prophet_model import SeriesForecast

DEFAULT_RELATIVE_MARGIN = 0.10  # 10% of the runner-up point forecast


@dataclass
class BusiestShift:
    month: date
    shift: str
    predicted: float
    lower: Optional[float]
    upper: Optional[float]
    runner_up: Optional[str] = None
    runner_up_predicted: Optional[float] = None
    runner_up_lower: Optional[float] = None
    runner_up_upper: Optional[float] = None
    margin: Optional[float] = None
    relative_margin: Optional[float] = None
    intervals_overlap: bool = False
    uncertain: bool = False
    reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "month": self.month.isoformat(),
            "shift": self.shift,
            "label": SERIES_LABELS.get(self.shift, self.shift),
            "predicted": round(self.predicted, 2),
            "lower": None if self.lower is None else round(self.lower, 2),
            "upper": None if self.upper is None else round(self.upper, 2),
            "runner_up": self.runner_up,
            "runner_up_predicted": (
                None if self.runner_up_predicted is None else round(self.runner_up_predicted, 2)
            ),
            "margin": None if self.margin is None else round(self.margin, 2),
            "relative_margin": (
                None if self.relative_margin is None else round(self.relative_margin, 4)
            ),
            "intervals_overlap": self.intervals_overlap,
            "uncertain": self.uncertain,
            "reason": self.reason,
        }


def _intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def identify_busiest_shift(
    shift_forecasts: dict[str, SeriesForecast],
    relative_margin: float = DEFAULT_RELATIVE_MARGIN,
) -> list[BusiestShift]:
    """Return the busiest shift for each forecast month across all shifts.

    ``shift_forecasts`` maps series name (``morning``/``afternoon``/``night``)
    to its :class:`SeriesForecast`. Only shifts present in every relevant month
    are compared; a month missing from a series is skipped for that series.
    """
    present = [name for name in SHIFT_SERIES if name in shift_forecasts]
    if len(present) < 2:
        raise ValueError("need at least two shift forecasts to compare")

    by_month: dict[date, dict[str, dict[str, float]]] = {}
    for name in present:
        for row in shift_forecasts[name].frame.itertuples(index=False):
            month = row.ds.date()
            by_month.setdefault(month, {})[name] = {
                "yhat": float(row.yhat),
                "lower": float(getattr(row, "yhat_lower", float("nan"))),
                "upper": float(getattr(row, "yhat_upper", float("nan"))),
            }

    results: list[BusiestShift] = []
    for month in sorted(by_month):
        candidates = by_month[month]
        if len(candidates) < 2:
            continue
        ordered = sorted(candidates.items(), key=lambda item: item[1]["yhat"], reverse=True)
        (top_name, top), (second_name, second) = ordered[0], ordered[1]

        margin = top["yhat"] - second["yhat"]
        relative = (margin / second["yhat"]) if second["yhat"] else None
        overlap = _intervals_overlap(
            (top["lower"], top["upper"]),
            (second["lower"], second["upper"]),
        )
        uncertain = overlap or (relative is not None and relative < relative_margin)
        reason = None
        if uncertain:
            parts = []
            if overlap:
                parts.append("80% intervals overlap")
            if relative is not None and relative < relative_margin:
                parts.append(f"relative margin < {relative_margin:.0%}")
            reason = "; ".join(parts)

        results.append(
            BusiestShift(
                month=month,
                shift=top_name,
                predicted=top["yhat"],
                lower=top["lower"],
                upper=top["upper"],
                runner_up=second_name,
                runner_up_predicted=second["yhat"],
                runner_up_lower=second["lower"],
                runner_up_upper=second["upper"],
                margin=margin,
                relative_margin=relative,
                intervals_overlap=overlap,
                uncertain=uncertain,
                reason=reason,
            )
        )
    return results


def busiest_shift_hit_rate(
    actuals_by_month: dict[date, dict[str, float]],
    predictions_by_month: dict[date, dict[str, float]],
    certain_months: Optional[set[date]] = None,
) -> dict:
    """Backtest the busiest-shift call against observed shift counts.

    Compares the predicted argmax shift with the observed argmax shift for
    every month present in both mappings. When ``certain_months`` is supplied
    (months whose comparison was flagged *not* uncertain), a separate hit rate
    is reported for those months.
    """
    months = sorted(set(actuals_by_month) & set(predictions_by_month))
    correct = 0
    certain_total = 0
    certain_correct = 0
    for month in months:
        actual = actuals_by_month[month]
        predicted = predictions_by_month[month]
        if not actual or not predicted:
            continue
        actual_top = max(actual, key=actual.get)
        predicted_top = max(predicted, key=predicted.get)
        is_correct = actual_top == predicted_top
        correct += int(is_correct)
        if certain_months is not None and month in certain_months:
            certain_total += 1
            certain_correct += int(is_correct)

    result = {
        "n_months": len(months),
        "correct": correct,
        "hit_rate": (correct / len(months)) if months else None,
    }
    if certain_months is not None:
        result["certain"] = {
            "n_months": certain_total,
            "correct": certain_correct,
            "hit_rate": (certain_correct / certain_total) if certain_total else None,
        }
    return result
