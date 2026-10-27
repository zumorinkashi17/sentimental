"""Shared constants for the call-volume forecasting pipeline.

The shift identifiers are the *verified* values from ``shift_catalog`` (see
Phase 1 report). There is deliberately **no shift id 2** in this database:

    shift_id 1 -> Morning   (06:00-14:00)
    shift_id 3 -> Afternoon (14:00-22:00)
    shift_id 4 -> Night     (22:00-06:00)

Forecasts are produced for the *recorded shift assignment* stored on each
call. As documented in Phase 1, that assignment does not always match the
clock time of ``session_time_called``, so a shift forecast describes the
recorded shift category, not a clock window.
"""

# Canonical series produced by the pipeline.
SERIES_TOTAL = "total"
SERIES_MORNING = "morning"
SERIES_AFTERNOON = "afternoon"
SERIES_NIGHT = "night"

ALL_SERIES = (SERIES_TOTAL, SERIES_MORNING, SERIES_AFTERNOON, SERIES_NIGHT)
SHIFT_SERIES = (SERIES_MORNING, SERIES_AFTERNOON, SERIES_NIGHT)

# series name -> verified shift_id
SERIES_TO_SHIFT_ID = {
    SERIES_MORNING: 1,
    SERIES_AFTERNOON: 3,
    SERIES_NIGHT: 4,
}

# shift_id -> human label
SHIFT_LABELS = {
    1: "Morning",
    3: "Afternoon",
    4: "Night",
}

# series name -> human label
SERIES_LABELS = {
    SERIES_TOTAL: "Total calls",
    SERIES_MORNING: "Morning shift",
    SERIES_AFTERNOON: "Afternoon shift",
    SERIES_NIGHT: "Night shift",
}

# Defaults for the validated training window (Phase 1 recommendation).
DEFAULT_TRAINING_START = "2020-01"  # inclusive, first month "YYYY-MM"
DEFAULT_FORECAST_HORIZON = 6        # months ahead
SUPPORTED_HORIZONS = (3, 6, 12)

# Prophet configuration defaults for monthly data.
PROPHET_INTERVAL_WIDTH = 0.80
PROPHET_CHANGEPOINT_PRIOR_SCALE = 0.05

# --------------------------------------------------------------------------- #
# Phase 3 selection decision (user-approved; do not silently change)
#
# Validation window (2024-09..2025-08) WAPE: yearly_off 16.56, yearly_on 17.91.
# Test window (2025-09..2026-04) WAPE: yearly_on 19.41, yearly_off 22.19.
# Yearly seasonality is *inconsistent* across windows, so it stays OFF because
# configuration was chosen on validation only. Persisted runs must record this
# config together with the evaluation snapshot so the choice is auditable.
# --------------------------------------------------------------------------- #
SELECTED_YEARLY_SEASONALITY = False
SELECTED_MODEL_CONFIG_NAME = "yearly_off"
SELECTED_RECONCILIATION_TOTAL_METHOD = "independent_total"
SELECTED_RECONCILIATION_SHIFT_METHOD = "raw"
