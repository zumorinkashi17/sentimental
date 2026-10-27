"""Prophet model fitting and monthly forecast generation.

Prophet runs inside the project's Python environment (management command /
service), never in the browser or a Supabase Edge Function. All four series
(total and the three shifts) use the same simple, reproducible configuration
appropriate for monthly observations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from .constants import (
    PROPHET_CHANGEPOINT_PRIOR_SCALE,
    PROPHET_INTERVAL_WIDTH,
    SELECTED_YEARLY_SEASONALITY,
)


def prophet_version() -> str:
    import prophet

    return getattr(prophet, "__version__", "unknown")


def selected_config() -> "ProphetConfig":
    """The user-approved production configuration (Phase 3: yearly OFF)."""
    return ProphetConfig(yearly_seasonality=SELECTED_YEARLY_SEASONALITY)


@dataclass
class ProphetConfig:
    """Documented, reproducible Prophet configuration for monthly data.

    Weekly and daily seasonality are permanently disabled because the
    observations are monthly aggregates; enabling them would invent
    intra-month structure that the data does not contain.
    """

    yearly_seasonality: bool = True
    weekly_seasonality: bool = False
    daily_seasonality: bool = False
    seasonality_mode: str = "additive"
    interval_width: float = PROPHET_INTERVAL_WIDTH
    changepoint_prior_scale: float = PROPHET_CHANGEPOINT_PRIOR_SCALE
    uncertainty_samples: int = 1000

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SeriesForecast:
    """Raw Prophet output for one series (no post-processing applied)."""

    series: str
    last_observed: date
    horizon: int
    frame: pd.DataFrame          # ds, yhat, yhat_lower, yhat_upper (raw)
    config: dict = field(default_factory=dict)
    prophet_version: str = ""

    @property
    def forecast_months(self) -> list[date]:
        return [ts.date() for ts in self.frame["ds"]]

    def clamped(self) -> pd.DataFrame:
        """Copy with negative call predictions clipped to zero.

        Kept separate from :attr:`frame` so evaluation always sees raw output.
        """
        out = self.frame.copy()
        for column in ("yhat", "yhat_lower", "yhat_upper"):
            if column in out:
                out[column] = out[column].clip(lower=0)
        return out


def fit_and_forecast(
    frame: pd.DataFrame,
    horizon: int,
    series: str = "total",
    config: Optional[ProphetConfig] = None,
) -> SeriesForecast:
    """Fit Prophet on a ``ds``/``y`` frame and forecast ``horizon`` months."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if frame is None or frame.empty:
        raise ValueError(f"series {series!r} has no observations to fit")
    if len(frame) < 2:
        raise ValueError(f"series {series!r} needs at least 2 observations")

    from prophet import Prophet

    config = config or ProphetConfig()
    data = frame[["ds", "y"]].copy()

    model = Prophet(
        yearly_seasonality=config.yearly_seasonality,
        weekly_seasonality=config.weekly_seasonality,
        daily_seasonality=config.daily_seasonality,
        seasonality_mode=config.seasonality_mode,
        interval_width=config.interval_width,
        changepoint_prior_scale=config.changepoint_prior_scale,
        uncertainty_samples=config.uncertainty_samples,
    )
    model.fit(data)

    future = model.make_future_dataframe(periods=horizon, freq="MS")
    predicted = model.predict(future)
    columns = [c for c in ("ds", "yhat", "yhat_lower", "yhat_upper") if c in predicted.columns]
    forecast = predicted[columns].tail(horizon).reset_index(drop=True)

    last_observed = pd.to_datetime(data["ds"]).max().date()
    return SeriesForecast(
        series=series,
        last_observed=last_observed,
        horizon=horizon,
        frame=forecast,
        config=config.as_dict(),
        prophet_version=prophet_version(),
    )


def forecast_all(
    series_frames: dict[str, pd.DataFrame],
    horizon: int,
    config: Optional[ProphetConfig] = None,
) -> dict[str, SeriesForecast]:
    """Fit and forecast every series in ``series_frames``."""
    return {
        name: fit_and_forecast(frame, horizon, series=name, config=config)
        for name, frame in series_frames.items()
    }
