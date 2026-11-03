"""Staffing estimation calculation service.

Reads the current persisted forecast run and backend-configured AHT values and
staffing assumptions, then produces a structured staffing estimate per forecast
month and shift.

This module never trains Prophet, never modifies forecast values, and never
reads mocked session metadata. It is a pure calculation over existing stored
forecast results plus backend-configured assumptions.

AHT and staffing assumptions are maintained directly in the backend code below
(see the STAFFING CONFIGURATION section). Changing values here updates staffing
recommendations without retraining Prophet or regenerating the forecast.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.utils import timezone

from apps.forecast.services import current_forecast_run, run_month_map
from apps.forecast.services.constants import (
    SERIES_TO_SHIFT_ID,
    SHIFT_SERIES,
    SERIES_TOTAL,
)
from apps.forecast.services.display import shift_catalog_hours


# ============================================================
# STAFFING CONFIGURATION
# ============================================================
# AHT VALUES ARE IN MINUTES.
#
# These are SAMPLE values. They are assumptions, not measured performance.
# Replace them with actual measured AHT values when real call-handling data
# becomes available. No database migration, model retraining, or forecast
# regeneration is required when these values change.
#
# DEFAULT_AHT_MINUTES applies to all shifts unless a shift-specific override
# is set. A shift override of None means "use DEFAULT_AHT_MINUTES".
# ============================================================

DEFAULT_AHT_MINUTES = Decimal("20.00")

MORNING_AHT_MINUTES = Decimal("25.00")      # None -> use DEFAULT_AHT_MINUTES
AFTERNOON_AHT_MINUTES = Decimal("25.00")    # None -> use DEFAULT_AHT_MINUTES
NIGHT_AHT_MINUTES = Decimal("30.00")        # None -> use DEFAULT_AHT_MINUTES

# Staffing assumptions (editable here, no admin UI required).
WORKING_DAYS_PER_MONTH = 22
SHRINKAGE_RATE = Decimal("0.15")      # 15% of working time lost to shrinkage
OCCUPANCY_FACTOR = Decimal("0.85")    # 85% of scheduled time productively handling calls
MIN_STAFF_MORNING = 2
MIN_STAFF_AFTERNOON = 2
MIN_STAFF_NIGHT = 2


def _aht_for_series(series: str) -> Optional[Decimal]:
    """Return the AHT in minutes for a given shift series.

    Returns None if no AHT is configured (global default is always set, so
    this only happens if DEFAULT_AHT_MINUTES is removed).
    """
    overrides = {
        "morning": MORNING_AHT_MINUTES,
        "afternoon": AFTERNOON_AHT_MINUTES,
        "night": NIGHT_AHT_MINUTES,
    }
    override = overrides.get(series)
    if override is not None:
        return override
    return DEFAULT_AHT_MINUTES


def _min_staff_for_series(series: str) -> int:
    """Return the minimum staffing requirement for a given shift series."""
    mapping = {
        "morning": MIN_STAFF_MORNING,
        "afternoon": MIN_STAFF_AFTERNOON,
        "night": MIN_STAFF_NIGHT,
    }
    return mapping.get(series, 0)


def _shift_duration_hours(start: time, end: time) -> float:
    """Return shift length in hours, handling shifts that cross midnight."""
    start_dt = datetime.combine(date.min, start)
    end_dt = datetime.combine(date.min, end)
    if end <= start:
        end_dt += timedelta(days=1)
    return (end_dt - start_dt).total_seconds() / 3600.0


class StaffingResult:
    """Structured result of a staffing calculation."""

    def __init__(
        self,
        *,
        available: bool,
        reason: Optional[str] = None,
        run_id: Optional[int] = None,
        run_generated_at: Optional[str] = None,
        aht_used: Optional[dict] = None,
        assumptions_used: Optional[dict] = None,
        months: Optional[list] = None,
        totals: Optional[dict] = None,
        calculation_timestamp: Optional[str] = None,
        config_version: Optional[str] = None,
    ):
        self.available = available
        self.reason = reason
        self.run_id = run_id
        self.run_generated_at = run_generated_at
        self.aht_used = aht_used or {}
        self.assumptions_used = assumptions_used or {}
        self.months = months or []
        self.totals = totals or {}
        self.calculation_timestamp = calculation_timestamp
        self.config_version = config_version

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "run_id": self.run_id,
            "run_generated_at": self.run_generated_at,
            "aht_used": self.aht_used,
            "assumptions_used": self.assumptions_used,
            "months": self.months,
            "totals": self.totals,
            "calculation_timestamp": self.calculation_timestamp,
            "config_version": self.config_version,
        }


def calculate_staffing(run=None) -> StaffingResult:
    """Calculate staffing estimates for the current forecast run.

    Parameters
    ----------
    run : ForecastRun | None
        The forecast run to use. Defaults to :func:`current_forecast_run`.

    Returns
    -------
    StaffingResult
        Structured calculation results.
    """
    if run is None:
        run = current_forecast_run()

    if run is None:
        return StaffingResult(
            available=False,
            reason="No forecast run has been persisted yet.",
        )

    data = run_month_map(run)
    months = sorted(data.get(SERIES_TOTAL, {}))

    # AHT values from backend configuration.
    aht_used = {}
    for series in SHIFT_SERIES:
        aht_val = _aht_for_series(series)
        aht_used[series] = {
            "minutes": aht_val,
            "status": "sample_default",
            "source": "Backend code default (sample value - not measured)",
            "is_sample": True,
            "used_global": aht_val == DEFAULT_AHT_MINUTES,
        }

    # Staffing assumptions from backend configuration.
    working_days = WORKING_DAYS_PER_MONTH
    shrinkage_rate = float(SHRINKAGE_RATE)
    occupancy_factor = float(OCCUPANCY_FACTOR)

    assumptions_used = {
        "working_days_per_month": working_days,
        "shrinkage_rate": shrinkage_rate,
        "occupancy_factor": occupancy_factor,
        "min_staff_morning": MIN_STAFF_MORNING,
        "min_staff_afternoon": MIN_STAFF_AFTERNOON,
        "min_staff_night": MIN_STAFF_NIGHT,
    }

    # Shift working hours from catalog.
    catalog = shift_catalog_hours()
    shift_hours_map = {}
    for series in SHIFT_SERIES:
        shift_id = SERIES_TO_SHIFT_ID.get(series)
        entry = catalog.get(shift_id)
        if entry:
            start = entry["start"]
            end = entry["end"]
            shift_hours_map[series] = _shift_duration_hours(start, end)
        else:
            shift_hours_map[series] = 8.0

    assumptions_used["shift_hours"] = shift_hours_map

    # Effective available hours per employee per month (shared across shifts).
    shrinkage_factor = 1.0 - shrinkage_rate
    scheduled_hours_per_month = shift_hours_map[SHIFT_SERIES[0]] * working_days
    effective_available_hours = (
        scheduled_hours_per_month * shrinkage_factor * occupancy_factor
    )

    month_results = []
    for month in months:
        shift_entries = []
        month_total_calls = 0.0
        month_total_workload = 0.0
        month_total_recommended = 0

        for series in SHIFT_SERIES:
            point = data.get(series, {}).get(month)
            if point is None:
                # Missing forecast month for this shift: do not treat as zero.
                continue

            forecast_calls = float(point["yhat"])
            aht_info = aht_used[series]
            aht_minutes = aht_info["minutes"]
            if aht_minutes is None:
                # No AHT configured at all: cannot calculate workload.
                continue

            aht_minutes = float(aht_minutes)
            workload_hours = forecast_calls * aht_minutes / 60.0

            # Workload-based staffing (fractional, preserved internally).
            if effective_available_hours > 0:
                workload_based_staff = workload_hours / effective_available_hours
            else:
                workload_based_staff = 0.0

            min_staff = _min_staff_for_series(series)
            recommended_staff = int(
                -(-max(workload_based_staff, min_staff) // 1)  # ceiling
            )
            if recommended_staff < min_staff:
                recommended_staff = min_staff

            shift_entries.append(
                {
                    "series": series,
                    "shift_name": (
                        {
                            "morning": "Morning Shift",
                            "afternoon": "Afternoon Shift",
                            "night": "Night Shift",
                        }.get(series, series.capitalize())
                    ),
                    "shift_hours": shift_hours_map[series],
                    "forecast_calls": round(forecast_calls, 2),
                    "aht_minutes": aht_minutes,
                    "aht_status": aht_info["status"],
                    "aht_source": aht_info["source"],
                    "aht_is_sample": aht_info["is_sample"],
                    "aht_used_global": aht_info["used_global"],
                    "workload_hours": round(workload_hours, 2),
                    "effective_available_hours": round(effective_available_hours, 2),
                    "workload_based_staff": round(workload_based_staff, 4),
                    "min_staff": min_staff,
                    "recommended_staff": recommended_staff,
                }
            )

            month_total_calls += forecast_calls
            month_total_workload += workload_hours
            month_total_recommended += recommended_staff

        # Total series value (independent forecast; may differ from shift sum).
        total_point = data.get(SERIES_TOTAL, {}).get(month)
        total_series_calls = None if total_point is None else float(total_point["yhat"])

        month_results.append(
            {
                "month": month.isoformat(),
                "month_label": _month_label(month),
                "shifts": shift_entries,
                "total_calls": round(month_total_calls, 2),
                "total_series_calls": None if total_series_calls is None else round(total_series_calls, 2),
                "total_workload_hours": round(month_total_workload, 2),
                "total_recommended_staff": month_total_recommended,
            }
        )

    # Aggregate totals across all months.
    totals = {
        "total_calls": round(sum(m["total_calls"] for m in month_results), 2),
        "total_workload_hours": round(sum(m["total_workload_hours"] for m in month_results), 2),
        "total_recommended_staff": sum(m["total_recommended_staff"] for m in month_results),
        "month_count": len(month_results),
    }

    return StaffingResult(
        available=True,
        run_id=run.run_id,
        run_generated_at=run.generated_at.isoformat(),
        aht_used=aht_used,
        assumptions_used=assumptions_used,
        months=month_results,
        totals=totals,
        calculation_timestamp=timezone.now().isoformat(),
        config_version=_config_version(aht_used, assumptions_used),
    )


def _config_version(aht_used: dict, assumptions_used: dict) -> str:
    """Produce a short traceable version string from the active configuration."""
    import hashlib

    payload = {
        "aht": {k: (str(v.get("minutes")) if v else None) for k, v in (aht_used or {}).items()},
        "assumptions": assumptions_used or {},
    }
    raw = repr(sorted(payload.items())).encode("utf-8")
    return "cfg-" + hashlib.sha1(raw).hexdigest()[:12]


def _month_label(month: date) -> str:
    from apps.forecast.services.display import month_name

    return month_name(month)


def ceil_value(value: float) -> int:
    """Round a positive float up to the nearest whole number."""
    if value <= 0:
        return 0
    return int(-(-value // 1))
