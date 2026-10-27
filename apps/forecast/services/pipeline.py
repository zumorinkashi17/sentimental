"""End-to-end forecasting pipeline: retrieve -> validate -> forecast.

This is the single entry point used by the management command (and, from
Phase 4 onward, by forecast persistence). It performs no database writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from .constants import ALL_SERIES, DEFAULT_FORECAST_HORIZON
from .data import MonthlyAggregates, aggregate_monthly
from .preprocess import (
    SeriesData,
    ValidationReport,
    build_all_series,
    resolve_window,
    validate_aggregates,
)
from .prophet_model import ProphetConfig, SeriesForecast, forecast_all, selected_config


class ForecastDataError(ValueError):
    """Raised when historical data fails validation and cannot be trained on."""

    def __init__(self, validation: ValidationReport):
        super().__init__("historical data failed validation:\n" + validation.summary())
        self.validation = validation


@dataclass
class ForecastRunResult:
    start: date
    end: date
    horizon: int
    aggregates: MonthlyAggregates
    validation: ValidationReport
    series: dict[str, SeriesData] = field(default_factory=dict)
    forecasts: dict[str, SeriesForecast] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_payload(self) -> dict:
        """JSON-serializable view of the run (used for exports / Phase 4)."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "training_start": self.start.isoformat(),
            "training_end": self.end.isoformat(),
            "last_observed_month": self.end.isoformat(),
            "horizon": self.horizon,
            "prophet_version": next(
                (f.prophet_version for f in self.forecasts.values()), ""
            ),
            "validation": {
                "is_valid": self.validation.is_valid,
                "missing_months": [d.isoformat() for d in self.validation.missing_months],
                "unknown_shift_months": {
                    d.isoformat(): v for d, v in self.validation.unknown_shift_months.items()
                },
                "reconciliation_failures": self.validation.reconciliation_failures,
                "zero_shift_months": {
                    k: [d.isoformat() for d in v]
                    for k, v in self.validation.zero_shift_months.items()
                },
            },
            "series": {
                name: {
                    "observations": data.observations,
                    "first": data.first.isoformat() if data.first else None,
                    "last": data.last.isoformat() if data.last else None,
                    "missing_months": [d.isoformat() for d in data.missing_months],
                }
                for name, data in self.series.items()
            },
            "forecasts": {
                name: [
                    {
                        "month": row.ds.date().isoformat(),
                        "yhat": round(float(row.yhat), 2),
                        "yhat_lower": round(float(row.yhat_lower), 2),
                        "yhat_upper": round(float(row.yhat_upper), 2),
                    }
                    for row in fc.frame.itertuples(index=False)
                ]
                for name, fc in self.forecasts.items()
            },
        }


def run_forecast_pipeline(
    start: Optional[date | str] = None,
    end: Optional[date | str] = None,
    horizon: int = DEFAULT_FORECAST_HORIZON,
    config: Optional[ProphetConfig] = None,
) -> ForecastRunResult:
    """Run the full pipeline over the resolved training window."""
    start, end = resolve_window(start, end)
    if end is None:
        raise ValueError("no historical observations available to train on")

    aggregates = aggregate_monthly(start=start, end=end)
    validation = validate_aggregates(aggregates)
    if not validation.is_valid:
        raise ForecastDataError(validation)

    series = build_all_series(aggregates)

    frames = {name: series[name].frame for name in ALL_SERIES if not series[name].frame.empty}
    forecasts = forecast_all(frames, horizon, config=config or selected_config())

    return ForecastRunResult(
        start=start,
        end=end,
        horizon=horizon,
        aggregates=aggregates,
        validation=validation,
        series=series,
        forecasts=forecasts,
    )
