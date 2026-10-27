"""Chronological evaluation of Prophet against a seasonal-naive baseline.

Design (agreed for Phase 3):

* Data is split chronologically - never shuffled. A rolling-origin
  ("walk-forward") backtest issues forecasts from a series of origins, each
  using only data available up to that origin, so no future information leaks
  into a prediction.
* The baseline is a *seasonal-naive* forecast: predict month ``t`` using the
  actual value from month ``t-12``.
* Metrics are MAE and WAPE, reported overall, per series, per model, per split
  region (validation/test) and per forecast horizon. WAPE is reported as
  ``None`` (with a reason) when its denominator is zero.
* Prophet is evaluated with and without yearly seasonality over the identical
  targets so seasonality is judged out-of-sample, not assumed.
* The total-vs-sum-of-shifts question is answered by comparing raw predictions
  on the same targets; nothing is silently adjusted.

This module performs no database writes and does not touch the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from .constants import ALL_SERIES, DEFAULT_FORECAST_HORIZON, SERIES_TOTAL
from .data import add_months, month_span
from .preprocess import SeriesData
from .prophet_model import ProphetConfig, fit_and_forecast

PROPHET = "prophet"
PROPHET_YEARLY_ON = "prophet_yearly_on"
PROPHET_YEARLY_OFF = "prophet_yearly_off"
SEASONAL_NAIVE = "seasonal_naive"

DEFAULT_MAX_HORIZON = 12

MODEL_LABELS = {
    PROPHET_YEARLY_ON: "yearly_on",
    PROPHET_YEARLY_OFF: "yearly_off",
}


def config_for_model(model_tag: str) -> ProphetConfig:
    """Build the Prophet config matching a model tag (weekly/daily always off)."""
    return ProphetConfig(yearly_seasonality=(model_tag == PROPHET_YEARLY_ON))


def model_tag_for_label(label: str) -> str:
    """Map 'yearly_on'/'yearly_off' (or the raw model tag) to a model tag."""
    if label in MODEL_LABELS:
        return label
    for tag, name in MODEL_LABELS.items():
        if name == label:
            return tag
    raise ValueError(f"unknown model label {label!r}; expected one of {tuple(MODEL_LABELS.values())}")


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@dataclass
class Metrics:
    n: int
    mae: Optional[float]
    wape: Optional[float]           # percent
    undefined_reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "mae": None if self.mae is None else round(self.mae, 3),
            "wape": None if self.wape is None else round(self.wape, 3),
            "undefined_reason": self.undefined_reason,
        }


def mae(actuals: Iterable[float], predictions: Iterable[float]) -> Optional[float]:
    pairs = [(a, p) for a, p in zip(actuals, predictions) if p is not None]
    if not pairs:
        return None
    return sum(abs(a - p) for a, p in pairs) / len(pairs)


def wape(actuals: Iterable[float], predictions: Iterable[float]) -> tuple[Optional[float], Optional[str]]:
    """Weighted absolute percentage error (%). Returns (value, reason-if-undefined)."""
    pairs = [(float(a), float(p)) for a, p in zip(actuals, predictions) if p is not None]
    if not pairs:
        return None, "no predictions"
    denominator = sum(abs(a) for a, _ in pairs)
    if denominator == 0:
        return None, "sum of actuals is zero (WAPE undefined)"
    return 100.0 * sum(abs(a - p) for a, p in pairs) / denominator, None


def metrics_from_rows(rows: list["ErrorRow"]) -> Metrics:
    if not rows:
        return Metrics(n=0, mae=None, wape=None, undefined_reason="no rows")
    m = mae((r.actual for r in rows), (r.predicted for r in rows))
    w, reason = wape((r.actual for r in rows), (r.predicted for r in rows))
    return Metrics(n=len(rows), mae=m, wape=w, undefined_reason=reason)


# --------------------------------------------------------------------------- #
# Error rows
# --------------------------------------------------------------------------- #
@dataclass
class ErrorRow:
    series: str
    model: str
    origin: date
    target: date
    horizon: int
    actual: float
    predicted: float

    @property
    def abs_error(self) -> float:
        return abs(self.actual - self.predicted)

    def as_dict(self) -> dict:
        return {
            "series": self.series,
            "model": self.model,
            "origin": self.origin.isoformat(),
            "target": self.target.isoformat(),
            "horizon": self.horizon,
            "actual": self.actual,
            "predicted": round(self.predicted, 3),
        }


def horizon_bucket(horizon: int) -> str:
    if horizon <= 3:
        return "1-3"
    if horizon <= 6:
        return "4-6"
    return "7-12"


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def seasonal_naive_predictions(frame: pd.DataFrame, origin: date, horizon: int) -> dict[date, Optional[float]]:
    """Predict ``origin+h`` from the actual value twelve months earlier."""
    lookup = {ts.date(): float(y) for ts, y in zip(frame["ds"], frame["y"])}
    out: dict[date, Optional[float]] = {}
    for h in range(1, horizon + 1):
        target = add_months(origin, h)
        out[target] = lookup.get(add_months(target, -12))
    return out


# --------------------------------------------------------------------------- #
# Walk-forward backtest
# --------------------------------------------------------------------------- #
def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def walk_forward(
    series: dict[str, SeriesData],
    origins: list[date],
    horizon: int,
    configs: Optional[dict[str, ProphetConfig]] = None,
    include_baseline: bool = True,
) -> list[ErrorRow]:
    """Rolling-origin backtest.

    Fits every Prophet configuration in ``configs`` (tagged by its key) and,
    optionally, the seasonal-naive baseline for each ``(series, origin)`` pair.
    Only targets with an observed actual are recorded.
    """
    configs = configs or {PROPHET: ProphetConfig()}
    rows: list[ErrorRow] = []
    for name, data in series.items():
        frame = data.frame
        if frame.empty:
            continue
        lookup = {ts.date(): float(y) for ts, y in zip(frame["ds"], frame["y"])}
        last_month = max(lookup)
        for origin in origins:
            train = frame[frame["ds"] <= pd.Timestamp(origin)]
            if len(train) < 2:
                continue
            step = min(horizon, _months_between(origin, last_month))
            if step < 1:
                continue

            for tag, config in configs.items():
                forecast = fit_and_forecast(train, step, series=name, config=config)
                for row in forecast.frame.itertuples(index=False):
                    target = row.ds.date()
                    actual = lookup.get(target)
                    if actual is None:
                        continue
                    rows.append(
                        ErrorRow(
                            name, tag, origin, target,
                            _months_between(origin, target), actual, float(row.yhat),
                        )
                    )

            if include_baseline:
                for target, value in seasonal_naive_predictions(frame, origin, step).items():
                    if value is None:
                        continue
                    actual = lookup.get(target)
                    if actual is None:
                        continue
                    rows.append(
                        ErrorRow(
                            name, SEASONAL_NAIVE, origin, target,
                            _months_between(origin, target), actual, value,
                        )
                    )
    return rows


# --------------------------------------------------------------------------- #
# Summaries and filters
# --------------------------------------------------------------------------- #
def filter_rows(
    rows: list[ErrorRow],
    models: Optional[Iterable[str]] = None,
    series: Optional[Iterable[str]] = None,
    targets_from: Optional[date] = None,
    targets_to: Optional[date] = None,
) -> list[ErrorRow]:
    result = rows
    if models is not None:
        allowed = set(models)
        result = [r for r in result if r.model in allowed]
    if series is not None:
        allowed = set(series)
        result = [r for r in result if r.series in allowed]
    if targets_from is not None:
        result = [r for r in result if r.target >= targets_from]
    if targets_to is not None:
        result = [r for r in result if r.target <= targets_to]
    return result


def summarize(rows: list[ErrorRow]) -> dict:
    """Overall metrics plus breakdowns by series, model, horizon bucket and horizon."""
    if not rows:
        empty = Metrics(0, None, None, "no rows").as_dict()
        return {"overall": empty, "by_model": {}, "by_series": {}, "by_horizon_bucket": {}, "by_horizon": {}}

    df = pd.DataFrame([r.as_dict() for r in rows])

    def group(sub: pd.DataFrame) -> dict:
        return metrics_from_rows(_rows_from_df(sub)).as_dict()

    return {
        "overall": group(df),
        "by_model": {model: group(sub) for model, sub in df.groupby("model")},
        "by_series": {
            f"{series}|{model}": group(sub)
            for (series, model), sub in df.groupby(["series", "model"])
        },
        "by_horizon_bucket": {
            f"{series}|{model}|h{bucket}": group(sub)
            for (series, model), sdf in df.groupby(["series", "model"])
            for bucket, sub in sdf.assign(bucket=sdf["horizon"].map(horizon_bucket)).groupby("bucket")
        },
        "by_horizon": {
            f"{series}|{model}|h{h}": group(sub)
            for (series, model), sdf in df.groupby(["series", "model"])
            for h, sub in sdf.groupby("horizon")
        },
    }


def _rows_from_df(df: pd.DataFrame) -> list[ErrorRow]:
    return [
        ErrorRow(
            series=row["series"],
            model=row["model"],
            origin=date.fromisoformat(row["origin"]),
            target=date.fromisoformat(row["target"]),
            horizon=int(row["horizon"]),
            actual=float(row["actual"]),
            predicted=float(row["predicted"]),
        )
        for _, row in df.iterrows()
    ]


# --------------------------------------------------------------------------- #
# Reconciliation (total vs sum of shifts)
# --------------------------------------------------------------------------- #
def detected_shift_sum(frame: pd.DataFrame) -> dict[date, float]:
    """Return ``{month: count}`` for a shift series frame."""
    return {ts.date(): float(y) for ts, y in zip(frame["ds"], frame["y"])}


def compare_reconciliation(
    actual_total_by_month: dict[date, float],
    independent_total: dict[date, float],
    shift_forecasts: dict[str, dict[date, float]],
) -> dict:
    """Compare two candidate total forecasts on the same, observed months.

    1. ``independent_total`` - the total model forecast directly.
    2. ``sum_of_shifts``    - the sum of the three raw shift forecasts.

    Raw model output is never modified. The discrepancy between the two is
    reported as ``residual_total_minus_shift_sum`` and is explicitly **not**
    called "unallocated calls".
    """
    names = list(shift_forecasts)
    months = sorted(m for m in actual_total_by_month if m in independent_total)

    independent_rows: list[ErrorRow] = []
    summed_rows: list[ErrorRow] = []
    residual: dict[str, float] = {}
    for month in months:
        actual = actual_total_by_month[month]
        ind = independent_total[month]
        shift_sum = sum(shift_forecasts[name].get(month, 0.0) for name in names)
        independent_rows.append(ErrorRow(SERIES_TOTAL, "independent_total", month, month, 0, actual, ind))
        summed_rows.append(ErrorRow(SERIES_TOTAL, "sum_of_shifts", month, month, 0, actual, shift_sum))
        residual[month.isoformat()] = round(ind - shift_sum, 4)

    return {
        "n_months": len(months),
        "independent_total": metrics_from_rows(independent_rows).as_dict(),
        "sum_of_shifts": metrics_from_rows(summed_rows).as_dict(),
        "residual_total_minus_shift_sum": residual,
    }


def reconcile_shifts(
    total_forecasts: dict[date, float],
    shift_forecasts: dict[str, dict[date, float]],
    method: str,
) -> dict[str, dict[date, float]]:
    """Reconcile independent shift forecasts against the independent total.

    ``method``:

    * ``raw``          - leave shift forecasts untouched.
    * ``proportional`` - scale each shift by ``independent_total / shift_sum``
      so the shifts sum to the independent total. This is an explicit,
      documented transformation; the input mappings are never mutated.
    """
    names = list(shift_forecasts)
    if method == "raw":
        return {name: dict(shift_forecasts[name]) for name in names}

    if method == "proportional":
        result = {name: dict(shift_forecasts[name]) for name in names}
        for month, total in total_forecasts.items():
            shift_sum = sum(shift_forecasts[name].get(month, 0.0) for name in names)
            factor = (total / shift_sum) if shift_sum else 0.0
            for name in names:
                if month in result[name]:
                    result[name][month] = result[name][month] * factor
        return result

    raise ValueError(f"unknown reconciliation method {method!r}")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass
class EvaluationSplit:
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def as_dict(self) -> dict:
        return {
            "validation": [self.validation_start.isoformat(), self.validation_end.isoformat()],
            "test": [self.test_start.isoformat(), self.test_end.isoformat()],
        }


def make_split(observed: list[date], test_months: int = 8, validation_months: int = 12) -> EvaluationSplit:
    """Chronologically split the observed months into validation then test windows."""
    if len(observed) < test_months + validation_months + 1:
        raise ValueError("not enough observed months for the requested split")
    test = observed[-test_months:]
    validation = observed[-(test_months + validation_months):-test_months]
    return EvaluationSplit(
        validation_start=validation[0],
        validation_end=validation[-1],
        test_start=test[0],
        test_end=test[-1],
    )


def make_origins(observed: list[date], end: date, count: int, max_horizon: int = DEFAULT_MAX_HORIZON) -> list[date]:
    """Choose walk-forward origins (months with enough future actuals).

    Origins are the most recent ``count`` observed months strictly before
    ``end``; each forecast horizon is truncated to the data actually available.
    """
    candidates = [m for m in month_span(observed[0], observed[-1]) if m in set(observed) and m < end]
    return candidates[-count:]


def run_evaluation(
    series: dict[str, SeriesData],
    split: EvaluationSplit,
    origins: list[date],
    max_horizon: int = DEFAULT_MAX_HORIZON,
) -> dict:
    """Run the full Phase 3 evaluation and return a JSON-serializable report."""
    configs = {
        PROPHET_YEARLY_ON: ProphetConfig(yearly_seasonality=True),
        PROPHET_YEARLY_OFF: ProphetConfig(yearly_seasonality=False),
    }
    all_rows = walk_forward(series, origins, max_horizon, configs=configs, include_baseline=True)

    validation_rows = filter_rows(all_rows, targets_from=split.validation_start, targets_to=split.validation_end)
    test_rows = filter_rows(all_rows, targets_from=split.test_start, targets_to=split.test_end)

    report = {
        "split": split.as_dict(),
        "origins": {
            "count": len(origins),
            "first": origins[0].isoformat() if origins else None,
            "last": origins[-1].isoformat() if origins else None,
        },
        "max_horizon": max_horizon,
        "validation": summarize(validation_rows),
        "test": summarize(test_rows),
        "seasonality": _seasonality_verdict(validation_rows, test_rows),
    }

    # Phase 3 decision (user-approved): yearly seasonality is OFF because it
    # performed better on the *validation* window. It must NOT be turned on
    # merely because it scores better on the held-out test window.
    report["selected_model"] = _select_model(report["seasonality"])
    report["reconciliation"] = _reconciliation_report(all_rows, split, report["selected_model"])
    report["busiest_shift"] = busiest_shift_report(series, split, max_horizon, all_rows, report["selected_model"])
    report["selection"] = select_methods(report)
    report["future"] = _future_section(series, split.test_end, DEFAULT_FORECAST_HORIZON, report["selection"])
    return report


def _select_model(seasonality: dict) -> str:
    """Choose the Prophet variant using validation-window WAPE only."""
    on_wape = seasonality.get("validation_wape_yearly_on")
    off_wape = seasonality.get("validation_wape_yearly_off")
    if on_wape is None or off_wape is None:
        return PROPHET_YEARLY_ON
    return PROPHET_YEARLY_ON if on_wape <= off_wape else PROPHET_YEARLY_OFF


def select_methods(report: dict) -> dict:
    """Choose configuration and reconciliation method using validation only.

    Deliberately never selects on the test window: doing so would leak the
    held-out period into model choice.
    """
    seasonality = report["seasonality"]
    on_wape = seasonality.get("validation_wape_yearly_on")
    off_wape = seasonality.get("validation_wape_yearly_off")
    config = None
    if on_wape is not None and off_wape is not None:
        config = "yearly_on" if on_wape <= off_wape else "yearly_off"

    validation = report["reconciliation"].get("validation") or {}
    independent = validation.get("independent_total") or {}
    summed = validation.get("sum_of_shifts") or {}
    total_method = None
    if independent.get("wape") is not None and summed.get("wape") is not None:
        total_method = "independent_total" if independent["wape"] <= summed["wape"] else "sum_of_shifts"

    shift_level = validation.get("shift_level") or {}
    raw = (shift_level.get("raw") or {}).get("overall") or {}
    proportional = (shift_level.get("proportional") or {}).get("overall") or {}
    shift_method = None
    if raw.get("wape") is not None and proportional.get("wape") is not None:
        shift_method = "raw" if raw["wape"] <= proportional["wape"] else "proportional"

    return {
        "selected_on": "validation",
        "config": config,
        "total_reconciliation_method": total_method,
        "shift_reconciliation_method": shift_method,
        "rationale": {
            "validation_wape_yearly_on": on_wape,
            "validation_wape_yearly_off": off_wape,
            "validation_wape_independent_total": independent.get("wape"),
            "validation_wape_sum_of_shifts": summed.get("wape"),
            "validation_wape_raw_shifts": raw.get("wape"),
            "validation_wape_proportional_shifts": proportional.get("wape"),
        },
    }


def _future_section(
    series: dict[str, SeriesData],
    origin: date,
    horizon: int,
    selection: dict,
) -> dict:
    """Forecast the future horizon with the selected config, documenting reconciliation."""
    from .busiest_shift import identify_busiest_shift

    config = ProphetConfig(yearly_seasonality=(selection.get("config") == "yearly_on"))
    forecasts = {}
    for name in ALL_SERIES:
        if name not in series or series[name].frame.empty:
            continue
        forecasts[name] = fit_and_forecast(series[name].frame, horizon, series=name, config=config)

    if SERIES_TOTAL not in forecasts:
        return {}

    total_by_month = {
        row.ds.date(): float(row.yhat) for row in forecasts[SERIES_TOTAL].frame.itertuples(index=False)
    }
    raw_shifts = {
        name: {row.ds.date(): float(row.yhat) for row in fc.frame.itertuples(index=False)}
        for name, fc in forecasts.items()
        if name in SHIFT_NAMES
    }
    method = selection.get("shift_reconciliation_method") or "raw"
    reconciled = reconcile_shifts(total_by_month, raw_shifts, method)

    shift_names = [name for name in SHIFT_NAMES if name in forecasts]
    busiest = identify_busiest_shift({name: forecasts[name] for name in shift_names}) if len(shift_names) >= 2 else []

    def series_rows(forecast) -> list[dict]:
        return [
            {
                "month": row.ds.date().isoformat(),
                "yhat": round(float(row.yhat), 2),
                "yhat_lower": round(float(row.yhat_lower), 2),
                "yhat_upper": round(float(row.yhat_upper), 2),
            }
            for row in forecast.frame.itertuples(index=False)
        ]

    return {
        "origin": origin.isoformat(),
        "horizon": horizon,
        "config": selection.get("config"),
        "shift_reconciliation_method": method,
        "total": series_rows(forecasts[SERIES_TOTAL]),
        "shifts_raw": {
            name: [
                {"month": month.isoformat(), "yhat": round(value, 2)}
                for month, value in sorted(raw_shifts[name].items())
            ]
            for name in raw_shifts
        },
        "shifts_reconciled": {
            name: [
                {"month": month.isoformat(), "yhat": round(value, 2)}
                for month, value in sorted(reconciled[name].items())
            ]
            for name in reconciled
        },
        "residual_total_minus_shift_sum": {
            month.isoformat(): round(total - sum(raw_shifts[name].get(month, 0.0) for name in raw_shifts), 2)
            for month, total in sorted(total_by_month.items())
        },
        "busiest_shift": [item.as_dict() for item in busiest],
    }


def _seasonality_verdict(validation_rows: list[ErrorRow], test_rows: list[ErrorRow]) -> dict:
    def wape_for(rows: list[ErrorRow], model: str) -> Optional[float]:
        subset = filter_rows(rows, models=[model])
        return metrics_from_rows(subset).wape

    val_on = wape_for(validation_rows, PROPHET_YEARLY_ON)
    val_off = wape_for(validation_rows, PROPHET_YEARLY_OFF)
    test_on = wape_for(test_rows, PROPHET_YEARLY_ON)
    test_off = wape_for(test_rows, PROPHET_YEARLY_OFF)

    improves = None
    if val_on is not None and val_off is not None:
        improves = val_on < val_off
    return {
        "validation_wape_yearly_on": val_on,
        "validation_wape_yearly_off": val_off,
        "test_wape_yearly_on": test_on,
        "test_wape_yearly_off": test_off,
        "yearly_helps_on_validation": improves,
    }


SHIFT_NAMES = ("morning", "afternoon", "night")


def _reconciliation_from_rows(
    rows: list[ErrorRow],
    targets_from: date,
    targets_to: date,
    model: str,
) -> dict:
    """Compare independent total vs sum-of-shifts over walk-forward predictions.

    Uses the exact same ``(origin, target)`` predictions that produced the main
    metrics, so the comparison is apples-to-apples across many origins. Raw
    predictions are read, never modified.
    """
    grouped: dict[tuple[date, date], dict[str, tuple[float, float]]] = {}
    for row in rows:
        if row.model != model:
            continue
        if not (targets_from <= row.target <= targets_to):
            continue
        grouped.setdefault((row.origin, row.target), {})[row.series] = (row.predicted, row.actual)

    independent_rows: list[ErrorRow] = []
    summed_rows: list[ErrorRow] = []
    raw_shift_rows: dict[str, list[ErrorRow]] = {name: [] for name in SHIFT_NAMES}
    scaled_shift_rows: dict[str, list[ErrorRow]] = {name: [] for name in SHIFT_NAMES}
    residuals: list[float] = []

    for (origin, target), values in grouped.items():
        if SERIES_TOTAL not in values or not all(name in values for name in SHIFT_NAMES):
            continue
        total_predicted, actual_total = values[SERIES_TOTAL]
        shift_sum = sum(values[name][0] for name in SHIFT_NAMES)
        horizon = _months_between(origin, target)
        independent_rows.append(
            ErrorRow(SERIES_TOTAL, "independent_total", origin, target, horizon, actual_total, total_predicted)
        )
        summed_rows.append(
            ErrorRow(SERIES_TOTAL, "sum_of_shifts", origin, target, horizon, actual_total, shift_sum)
        )
        residuals.append(total_predicted - shift_sum)

        factor = (total_predicted / shift_sum) if shift_sum else 0.0
        for name in SHIFT_NAMES:
            predicted_shift, actual_shift = values[name]
            raw_shift_rows[name].append(
                ErrorRow(name, "raw_shifts", origin, target, horizon, actual_shift, predicted_shift)
            )
            scaled_shift_rows[name].append(
                ErrorRow(name, "scaled_shifts", origin, target, horizon, actual_shift, predicted_shift * factor)
            )

    if not independent_rows:
        return {"n_cases": 0, "independent_total": None, "sum_of_shifts": None}

    residual_summary = {
        "n": len(residuals),
        "mean": round(sum(residuals) / len(residuals), 4),
        "mean_abs": round(sum(abs(r) for r in residuals) / len(residuals), 4),
        "max_abs": round(max(abs(r) for r in residuals), 4),
    }

    def shift_summary(store: dict[str, list[ErrorRow]]) -> dict:
        per_series = {name: metrics_from_rows(items).as_dict() for name, items in store.items()}
        all_rows = [row for items in store.values() for row in items]
        return {"overall": metrics_from_rows(all_rows).as_dict(), "by_series": per_series}

    return {
        "n_cases": len(independent_rows),
        "independent_total": metrics_from_rows(independent_rows).as_dict(),
        "sum_of_shifts": metrics_from_rows(summed_rows).as_dict(),
        # Shift-level accuracy: raw vs proportionally scaled to the independent total.
        "shift_level": {
            "raw": shift_summary(raw_shift_rows),
            "proportional": shift_summary(scaled_shift_rows),
        },
        # NOTE: this is a forecast discrepancy, explicitly NOT "unallocated calls".
        "residual_total_minus_shift_sum": residual_summary,
    }


def _reconciliation_report(all_rows: list[ErrorRow], split: EvaluationSplit, model: str) -> dict:
    return {
        "validation": _reconciliation_from_rows(all_rows, split.validation_start, split.validation_end, model),
        "test": _reconciliation_from_rows(all_rows, split.test_start, split.test_end, model),
    }


def busiest_shift_backtest(
    shift_rows: list[ErrorRow],
    targets_from: Optional[date] = None,
    targets_to: Optional[date] = None,
    horizons: Optional[Iterable[int]] = None,
) -> dict:
    """Hit rate of the predicted busiest shift using walk-forward predictions.

    Every ``(origin, target)`` pair pools the three shift point forecasts; the
    predicted argmax shift is compared with the observed argmax shift.
    """
    allowed_horizons = set(horizons) if horizons is not None else None
    predicted: dict[tuple[date, date], dict[str, float]] = {}
    actual: dict[date, dict[str, float]] = {}
    for row in shift_rows:
        if targets_from is not None and row.target < targets_from:
            continue
        if targets_to is not None and row.target > targets_to:
            continue
        if allowed_horizons is not None and row.horizon not in allowed_horizons:
            continue
        predicted.setdefault((row.origin, row.target), {})[row.series] = row.predicted
        actual.setdefault(row.target, {})[row.series] = row.actual

    total = 0
    correct = 0
    for target, pred in predicted.items():
        observed = actual.get(target[1], {})
        if len(pred) < 2 or len(observed) < 2:
            continue
        total += 1
        if max(pred, key=pred.get) == max(observed, key=observed.get):
            correct += 1
    return {
        "n_cases": total,
        "correct": correct,
        "hit_rate": (correct / total) if total else None,
    }


def busiest_shift_report(
    series: dict[str, SeriesData],
    split: EvaluationSplit,
    max_horizon: int,
    all_rows: list[ErrorRow],
    model: str,
) -> dict:
    """Predicted busiest shift per test month + historical hit rates."""
    from .busiest_shift import identify_busiest_shift

    shift_names = [name for name in SHIFT_NAMES if name in series]
    if len(shift_names) < 2:
        return {}

    origin = split.validation_end
    step = min(max_horizon, _months_between(origin, split.test_end))
    if step < 1:
        return {}

    config = ProphetConfig(yearly_seasonality=(model == PROPHET_YEARLY_ON))
    forecasts = {}
    for name in shift_names:
        frame = series[name].frame
        train = frame[frame["ds"] <= pd.Timestamp(origin)]
        forecasts[name] = fit_and_forecast(train, step, series=name, config=config)

    predictions = identify_busiest_shift(forecasts)
    test_predictions = [p for p in predictions if split.test_start <= p.month <= split.test_end]

    shift_rows = filter_rows(all_rows, models=[model], series=shift_names)

    def hit_rates(targets_from: date, targets_to: date) -> dict:
        return {
            "all": busiest_shift_backtest(shift_rows, targets_from, targets_to),
            "h1": busiest_shift_backtest(shift_rows, targets_from, targets_to, horizons=[1]),
            "h1_3": busiest_shift_backtest(shift_rows, targets_from, targets_to, horizons=[1, 2, 3]),
            "h1_6": busiest_shift_backtest(shift_rows, targets_from, targets_to, horizons=[1, 2, 3, 4, 5, 6]),
        }

    return {
        "origin": origin.isoformat(),
        "model": model,
        "validation_hit_rate": hit_rates(split.validation_start, split.validation_end),
        "test_hit_rate": hit_rates(split.test_start, split.test_end),
        "predictions": [p.as_dict() for p in test_predictions],
        "uncertain_months": [p.month.isoformat() for p in test_predictions if p.uncertain],
    }
