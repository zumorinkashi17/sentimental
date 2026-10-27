"""Persistence and read path for forecast runs.

A ``ForecastRun`` is an append-only artifact. Generating a new run never
overwrites an existing run; at most it moves the single ``is_current`` pointer
that the Dashboard / Call Volume Forecast / Shift Schedules pages all read, so
those three pages always see the *same* run.

Historical ``call_session`` rows are never modified here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone as django_timezone

from apps.forecast.models import ForecastRun, ForecastRunMonth
from .constants import ALL_SERIES, SHIFT_SERIES, SERIES_LABELS, SERIES_TO_SHIFT_ID
from .data import add_months, month_span, month_start
from .pipeline import ForecastRunResult
from .preprocess import ValidationReport


def _month_map(forecast) -> dict[date, dict[str, float]]:
    """``{month: {yhat, yhat_lower, yhat_upper}}`` for one SeriesForecast."""
    out: dict[date, dict[str, float]] = {}
    for row in forecast.frame.itertuples(index=False):
        out[row.ds.date()] = {
            "yhat": float(row.yhat),
            "yhat_lower": float(getattr(row, "yhat_lower", float("nan"))),
            "yhat_upper": float(getattr(row, "yhat_upper", float("nan"))),
        }
    return out


@transaction.atomic
def persist_forecast_run(
    result: ForecastRunResult,
    *,
    model_config_name: str,
    yearly_seasonality: bool,
    reconciliation_total_method: str = "independent_total",
    reconciliation_shift_method: str = "raw",
    evaluation_snapshot: Optional[dict] = None,
    is_current: bool = True,
    generation_metadata: Optional[dict] = None,
) -> ForecastRun:
    """Persist one forecast run and all its monthly rows.

    The residual ``total yhat - sum(shift yhat)`` is stored per month on the
    ``total`` row. It is a *forecast discrepancy*, never redistributed across
    shifts and never labelled "unallocated calls".

    ``generation_metadata`` (horizon, forecast window, unobserved months) is
    kept inside the existing ``evaluation_snapshot`` JSON, so no schema change
    is needed for a run to record how it was produced.
    """
    forecast_maps = {name: _month_map(fc) for name, fc in result.forecasts.items()}
    months = sorted(set().union(*forecast_maps.values())) if forecast_maps else []

    snapshot = dict(evaluation_snapshot or {})
    if generation_metadata:
        snapshot["generation"] = generation_metadata

    run = ForecastRun.objects.create(
        generated_at=result.generated_at,
        training_start=result.start,
        training_end=result.end,
        last_observed_month=result.end,
        horizon_months=result.horizon,
        prophet_version=next((fc.prophet_version for fc in result.forecasts.values()), ""),
        model_config_name=model_config_name,
        yearly_seasonality=yearly_seasonality,
        model_config=(next(iter(result.forecasts.values())).config if result.forecasts else {}),
        reconciliation_total_method=reconciliation_total_method,
        reconciliation_shift_method=reconciliation_shift_method,
        validation=_validation_payload(result.validation),
        evaluation_snapshot=snapshot,
    )

    rows: list[ForecastRunMonth] = []
    for month in months:
        shift_sum = sum(
            forecast_maps.get(name, {}).get(month, {}).get("yhat", 0.0) for name in SHIFT_SERIES
        )
        total_yhat = forecast_maps.get("total", {}).get(month, {}).get("yhat")
        residual = (total_yhat - shift_sum) if total_yhat is not None else None

        for name in ALL_SERIES:
            values = forecast_maps.get(name, {}).get(month)
            if values is None:
                continue
            rows.append(
                ForecastRunMonth(
                    run=run,
                    month=month,
                    series=name,
                    yhat=values["yhat"],
                    yhat_lower=values["yhat_lower"],
                    yhat_upper=values["yhat_upper"],
                    residual_total_minus_shift_sum=residual if name == "total" else None,
                )
            )
    ForecastRunMonth.objects.bulk_create(rows)

    if is_current:
        run.make_current()
    return run


def _validation_payload(validation: ValidationReport) -> dict:
    return {
        "is_valid": validation.is_valid,
        "start": validation.start.isoformat() if validation.start else None,
        "end": validation.end.isoformat() if validation.end else None,
        "missing_months": [d.isoformat() for d in validation.missing_months],
        "unknown_shift_months": {
            d.isoformat(): v for d, v in validation.unknown_shift_months.items()
        },
        "reconciliation_failures": [
            {**failure, "month": failure["month"].isoformat()}
            for failure in validation.reconciliation_failures
        ],
        "zero_shift_months": {
            name: [d.isoformat() for d in months]
            for name, months in validation.zero_shift_months.items()
        },
        "warnings": list(validation.warnings),
        "issues": list(validation.issues),
    }


# --------------------------------------------------------------------------- #
# Read path (shared by the three application pages)
# --------------------------------------------------------------------------- #
def current_forecast_run() -> Optional[ForecastRun]:
    """The single run every page must use, or ``None`` if none has been stored."""
    return ForecastRun.objects.filter(is_current=True).order_by("-generated_at").first()


def get_forecast_run(run_id: int) -> Optional[ForecastRun]:
    return ForecastRun.objects.filter(pk=run_id).first()


def run_month_map(run: ForecastRun) -> dict[str, dict[date, dict[str, float]]]:
    """``{series: {month: {yhat, yhat_lower, yhat_upper, residual}}}`` for one run."""
    out: dict[str, dict[date, dict[str, float]]] = {name: {} for name in ALL_SERIES}
    rows = run.months.order_by("month", "series")
    for row in rows:
        out[row.series][row.month] = {
            "yhat": row.yhat,
            "yhat_lower": row.yhat_lower,
            "yhat_upper": row.yhat_upper,
            "residual_total_minus_shift_sum": row.residual_total_minus_shift_sum,
        }
    return out


def month_totals(run: ForecastRun) -> list[dict]:
    """Total-calls view of a run: month, yhat, interval, residual."""
    data = run_month_map(run)
    out = []
    for month, values in sorted(data["total"].items()):
        out.append(
            {
                "month": month.isoformat(),
                "yhat": round(values["yhat"], 2),
                "yhat_lower": None if values["yhat_lower"] is None else round(values["yhat_lower"], 2),
                "yhat_upper": None if values["yhat_upper"] is None else round(values["yhat_upper"], 2),
                "residual_total_minus_shift_sum": (
                    None
                    if values["residual_total_minus_shift_sum"] is None
                    else round(values["residual_total_minus_shift_sum"], 2)
                ),
            }
        )
    return out


def busiest_shifts(run: ForecastRun) -> list[dict]:
    """Predicted busiest shift per month, with the documented uncertainty flag.

    A month is uncertain when the top two 80% intervals overlap or the
    relative point margin is below 10% - see
    :func:`apps.forecast.services.busiest_shift.identify_busiest_shift`.
    """
    from .busiest_shift import identify_busiest_shift
    from .prophet_model import SeriesForecast

    data = run_month_map(run)
    forecasts: dict[str, SeriesForecast] = {}
    for name in SHIFT_SERIES:
        months = sorted(data[name])
        if not months:
            continue
        import pandas as pd

        frame = pd.DataFrame(
            {
                "ds": pd.to_datetime(months),
                "yhat": [data[name][m]["yhat"] for m in months],
                "yhat_lower": [data[name][m]["yhat_lower"] for m in months],
                "yhat_upper": [data[name][m]["yhat_upper"] for m in months],
            }
        )
        forecasts[name] = SeriesForecast(
            series=name,
            last_observed=run.last_observed_month,
            horizon=len(months),
            frame=frame,
        )
    if len(forecasts) < 2:
        return []
    return [item.as_dict() for item in identify_busiest_shift(forecasts)]


def _freshness(run: ForecastRun) -> dict:
    """How current is this run relative to the calendar?

    ``elapsed_months`` are published months that have already passed - a run
    made entirely of them must not be read as a current future forecast.
    ``gap_months`` are the months between the training cutoff and the current
    month; they have no usable observations, so the projection across them is
    provisional.

    The wording is deliberately plain: the page is read by helpline managers,
    not by statisticians. Missing months are never described as zero calls.
    """
    from .display import month_name, month_range_label

    as_of = month_start(django_timezone.localdate())
    published = sorted(run_month_map(run)["total"])
    elapsed = [month for month in published if month <= as_of]
    gap = month_span(add_months(run.training_end, 1), as_of)

    notes: list[str] = []
    action: Optional[str] = None

    if elapsed:
        notes.append(
            f"This forecast covers months that have already passed "
            f"(last month {month_name(published[-1])}). Generate an updated "
            "forecast to plan ahead."
        )
    if gap:
        notes.append(
            f"Historical call data is available through {month_name(run.training_end)}. "
            f"Usable records for {month_range_label(gap[0], gap[-1])} are missing or "
            "unverified, so this forecast is preliminary and may be less accurate."
        )
        action = (
            "Action needed: Check whether these records are missing or have not been "
            "imported. Restore actual records if available, then generate an "
            "updated forecast."
        )

    return {
        "as_of": as_of.isoformat(),
        "published_start": published[0].isoformat() if published else None,
        "published_end": published[-1].isoformat() if published else None,
        "elapsed_months": [month.isoformat() for month in elapsed],
        "gap_months": [month.isoformat() for month in gap],
        "is_stale": bool(elapsed),
        "is_provisional": bool(gap),
        "notes": notes,
        "action": action,
        # Plain-language labels used by the three pages.
        "historical_available_through": month_name(run.training_end),
        "missing_range_label": month_range_label(gap[0], gap[-1]) if gap else None,
        "missing_month_count": len(gap),
        "forecast_period": month_range_label(
            published[0] if published else None, published[-1] if published else None
        ),
    }


def forecast_run_payload(run: Optional[ForecastRun]) -> dict:
    """Everything the three application pages need, from one persisted run."""
    from .display import (
        enrich_busiest_shifts,
        format_timestamp,
        month_range_label,
        shift_display_map,
    )

    if run is None:
        return {"available": False, "reason": "No forecast run has been persisted yet."}

    evaluation = run.evaluation_snapshot or {}
    freshness = _freshness(run)
    shift_labels = shift_display_map(SERIES_TO_SHIFT_ID)
    published = sorted(run_month_map(run)["total"])

    return {
        "available": True,
        "run_id": run.run_id,
        # ``generated_at`` stays the raw stored value (UTC, machine readable).
        # ``generated_display`` is the same moment shown in the app timezone.
        "generated_at": run.generated_at.isoformat(),
        "generated_display": format_timestamp(run.generated_at),
        "training_start": run.training_start.isoformat(),
        "training_end": run.training_end.isoformat(),
        "last_observed_month": run.last_observed_month.isoformat(),
        "horizon_months": run.horizon_months,
        "prophet_version": run.prophet_version,
        "model_config_name": run.model_config_name,
        "yearly_seasonality": run.yearly_seasonality,
        "reconciliation_total_method": run.reconciliation_total_method,
        "reconciliation_shift_method": run.reconciliation_shift_method,
        "months": month_totals(run),
        "busiest_shifts": enrich_busiest_shifts(busiest_shifts(run), shift_labels),
        "validation": run.validation,
        "generation": evaluation.get("generation") or {},
        "freshness": freshness,
        # Plain-language labels shared by all three pages.
        "shift_labels": shift_labels,
        "historical_available_through": freshness["historical_available_through"],
        "historical_data_used": month_range_label(run.training_start, run.training_end),
        "forecast_period": freshness["forecast_period"],
        "forecast_method": (
            "Monthly trend model"
            + ("" if run.yearly_seasonality else " (no yearly seasonal pattern)")
        ),
        "evaluation": {
            "split": evaluation.get("split"),
            "selected_model": evaluation.get("selected_model"),
            "seasonality": evaluation.get("seasonality"),
            "note": (
                "Past accuracy was checked on data from September 2025 to April "
                "2026 only, so historical model performance may not reflect "
                "future performance."
            ),
        },
        "caveats": [
            "Forecasts are estimates, not guaranteed results.",
            "Missing historical data may reduce accuracy.",
            "The busiest shift may be uncertain when the estimated ranges overlap.",
            "Total and shift-level forecasts are calculated separately, so they may "
            "not add up exactly.",
            "Historical model performance may not reflect future performance.",
            "Shift estimates depend on the shift recorded on each call, which may "
            "not match the clock time of the call.",
        ],
    }
