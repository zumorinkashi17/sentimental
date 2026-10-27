"""Interactive forecast generation for the Call Volume Forecast page.

Policy (approved by the user before implementation):

* The **published** window always starts in the month *after* the current
  calendar month, so a run whose window has already elapsed is never presented
  as the current future forecast.
* The pipeline still trains on the validated training window (the latest
  contiguous run of usable history). When that window ends before the current
  month, the model has to project across the unobserved months in between, so
  the *generation* horizon is ``gap + requested horizon`` while exactly the
  requested number of future months is published.
* Prophet's point forecast for a given month is a function of the fitted model
  and the forecast date, not of the requested horizon, so extending the
  generation horizon never changes a published value - it only reaches further
  ahead. The 80% interval bounds carry Prophet's Monte-Carlo noise and are
  therefore never compared between runs.
* Missing history is never imputed, interpolated or zero-filled. Months without
  usable observations are excluded from training and recorded in the run
  metadata as unobserved months.
* A run is published only after generation *and* validation succeed. If
  anything fails, nothing is written and the previously current run stays
  current.
"""

from __future__ import annotations

import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator, Optional

from django.db import connection, transaction
from django.utils import timezone as django_timezone

from apps.forecast.models import ForecastRun
from .constants import (
    ALL_SERIES,
    SELECTED_MODEL_CONFIG_NAME,
    SELECTED_RECONCILIATION_SHIFT_METHOD,
    SELECTED_RECONCILIATION_TOTAL_METHOD,
    SELECTED_YEARLY_SEASONALITY,
    SUPPORTED_HORIZONS,
)
from .data import add_months, month_span, month_start
from .pipeline import ForecastRunResult, run_forecast_pipeline
from .preprocess import resolve_window
from .prophet_model import ProphetConfig, selected_config
from .storage import current_forecast_run, persist_forecast_run


class GenerationError(Exception):
    """Raised when a forecast cannot be generated, validated or published."""


class GenerationBusy(GenerationError):
    """Raised when another generation request is already in flight."""


# Process-level guard: two concurrent requests must never fit two models at
# the same time and race for the current-run pointer.
_GENERATION_LOCK = threading.Lock()


@contextmanager
def generation_lock() -> Iterator[None]:
    """Serialise generation attempts inside this process."""
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise GenerationBusy(
            "A forecast is already being generated. Please wait for it to finish."
        )
    try:
        yield
    finally:
        _GENERATION_LOCK.release()


def generation_in_progress() -> bool:
    """Whether a generation is currently running in this process."""
    return _GENERATION_LOCK.locked()


def validate_horizon(horizon) -> int:
    """Return the validated horizon, or raise :class:`GenerationError`."""
    try:
        value = int(horizon)
    except (TypeError, ValueError):
        raise GenerationError(
            f"Unsupported forecast horizon: {horizon!r}. Choose 3, 6 or 12 months."
        )
    if value not in SUPPORTED_HORIZONS:
        raise GenerationError(
            f"Unsupported forecast horizon: {value}. Choose 3, 6 or 12 months."
        )
    return value


@dataclass
class GenerationPlan:
    """What a requested horizon resolves to before anything is fitted."""

    horizon: int
    training_start: date
    training_end: date
    as_of: date
    forecast_start: date
    forecast_end: date
    generation_horizon: int
    unobserved_months: list[date] = field(default_factory=list)

    @property
    def provisional(self) -> bool:
        """True when the model had to project across unobserved months."""
        return bool(self.unobserved_months)

    @property
    def published_months(self) -> list[date]:
        """The exact months that will be stored and shown."""
        return month_span(self.forecast_start, self.forecast_end)

    def as_metadata(self) -> dict:
        """JSON-serializable description stored with the run."""
        return {
            "policy": "future_anchored",
            "requested_horizon": self.horizon,
            "generation_horizon": self.generation_horizon,
            "as_of": self.as_of.isoformat(),
            "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(),
            "forecast_start": self.forecast_start.isoformat(),
            "forecast_end": self.forecast_end.isoformat(),
            "published_months": [m.isoformat() for m in self.published_months],
            "unobserved_months": [m.isoformat() for m in self.unobserved_months],
            "provisional": self.provisional,
            "note": (
                "The forecast window starts after the current month so an elapsed "
                "run is never presented as a current future forecast. Months "
                "between the training cutoff and the forecast window have no "
                "usable observations; they were excluded from training and were "
                "not imputed."
            ),
        }


def plan_generation(horizon, as_of: Optional[date] = None) -> GenerationPlan:
    """Resolve a requested horizon into concrete training and forecast windows.

    ``as_of`` defaults to the current month and exists so the policy can be
    exercised deterministically in tests.
    """
    horizon = validate_horizon(horizon)

    training_start, training_end = resolve_window()
    if training_end is None:
        raise GenerationError(
            "No historical observations are available to train on, so no forecast "
            "was generated."
        )

    as_of = month_start(as_of or django_timezone.localdate())
    forecast_start = max(add_months(as_of, 1), add_months(training_end, 1))
    unobserved = month_span(add_months(training_end, 1), as_of)
    generation_horizon = len(unobserved) + horizon
    forecast_end = add_months(forecast_start, horizon - 1)

    return GenerationPlan(
        horizon=horizon,
        training_start=training_start,
        training_end=training_end,
        as_of=as_of,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
        generation_horizon=generation_horizon,
        unobserved_months=unobserved,
    )


def _restrict_to_published_window(
    result: ForecastRunResult, plan: GenerationPlan
) -> ForecastRunResult:
    """Keep only the months the plan publishes.

    The months between the training cutoff and the published window are model
    output for periods nobody can use yet; they are dropped from the run and
    recorded as unobserved months instead.
    """
    published = {month.isoformat() for month in plan.published_months}
    for forecast in result.forecasts.values():
        frame = forecast.frame
        mask = frame["ds"].dt.strftime("%Y-%m-%d").isin(published)
        forecast.frame = frame[mask].reset_index(drop=True)
        forecast.horizon = plan.horizon
    result.horizon = plan.horizon
    return result


def generate_forecast(
    horizon,
    as_of: Optional[date] = None,
    config: Optional[ProphetConfig] = None,
) -> tuple[ForecastRunResult, GenerationPlan]:
    """Fit the model and return the run restricted to the published window."""
    plan = plan_generation(horizon, as_of=as_of)
    result = run_forecast_pipeline(
        start=plan.training_start,
        end=plan.training_end,
        horizon=plan.generation_horizon,
        config=config or selected_config(),
    )
    return _restrict_to_published_window(result, plan), plan


def validate_generated_run(result: ForecastRunResult, plan: GenerationPlan) -> list[str]:
    """Return the problems found in a generated run (empty list means valid)."""
    problems: list[str] = []
    expected = [month.isoformat() for month in plan.published_months]

    for name in ALL_SERIES:
        forecast = result.forecasts.get(name)
        if forecast is None:
            problems.append(f"series '{name}' is missing from the generated forecast")
            continue
        months = [row.ds.date().isoformat() for row in forecast.frame.itertuples(index=False)]
        if months != expected:
            problems.append(
                f"series '{name}' produced {len(months)} month(s) instead of "
                f"{len(expected)}"
            )
        for row in forecast.frame.itertuples(index=False):
            if not math.isfinite(float(row.yhat)):
                problems.append(
                    f"series '{name}' has a non-finite forecast for {row.ds:%Y-%m}"
                )
                break
    return problems


def _publish(run: ForecastRun) -> None:
    """Move the current-run pointer, serialised against other processes."""
    with transaction.atomic():
        if connection.features.has_select_for_update:
            ForecastRun.objects.select_for_update().filter(is_current=True).first()
        run.make_current()


def publish_generation(
    result: ForecastRunResult,
    plan: GenerationPlan,
    *,
    evaluation_snapshot: Optional[dict] = None,
    model_config_name: str = SELECTED_MODEL_CONFIG_NAME,
    yearly_seasonality: bool = SELECTED_YEARLY_SEASONALITY,
    reconciliation_total_method: str = SELECTED_RECONCILIATION_TOTAL_METHOD,
    reconciliation_shift_method: str = SELECTED_RECONCILIATION_SHIFT_METHOD,
) -> ForecastRun:
    """Store a validated run and publish it as the current run.

    The run is written first and published afterwards, both inside one
    transaction: if anything fails nothing is stored and the previously current
    run stays current.
    """
    problems = validate_generated_run(result, plan)
    if problems:
        raise GenerationError(
            "The generated forecast failed validation and was not published: "
            + "; ".join(problems)
        )

    with transaction.atomic():
        run = persist_forecast_run(
            result,
            model_config_name=model_config_name,
            yearly_seasonality=yearly_seasonality,
            reconciliation_total_method=reconciliation_total_method,
            reconciliation_shift_method=reconciliation_shift_method,
            evaluation_snapshot=evaluation_snapshot,
            is_current=False,
            generation_metadata=plan.as_metadata(),
        )
        _publish(run)
    return run


def reusable_evaluation_snapshot() -> dict:
    """Carry the stored evaluation evidence forward to the next run.

    The model configuration is not re-selected per horizon, so the recorded
    evaluation stays valid for the new run and keeps the choice auditable.
    """
    run = current_forecast_run()
    if run is None:
        return {}
    snapshot = dict(run.evaluation_snapshot or {})
    snapshot.pop("generation", None)
    return snapshot
