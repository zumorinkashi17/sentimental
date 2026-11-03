"""Public API for the forecasting service layer.

Layout:
    constants.py      verified shift mapping, defaults, selected config
    data.py           read-only retrieval + monthly aggregation
    preprocess.py     validation and per-series preparation
    prophet_model.py  Prophet configuration, fitting, prediction
    pipeline.py       orchestration of the three steps above
    evaluate.py       chronological evaluation vs seasonal-naive baseline
    busiest_shift.py  provisional busiest-shift prediction + uncertainty
    storage.py        persistence + shared read path for the UI pages
    generation.py     future-anchored generation and publication of a run
    display.py        plain-language labels, shift hours and timezone display
"""

from .constants import (  # noqa: F401
    ALL_SERIES,
    DEFAULT_FORECAST_HORIZON,
    DEFAULT_TRAINING_START,
    PROPHET_CHANGEPOINT_PRIOR_SCALE,
    PROPHET_INTERVAL_WIDTH,
    SELECTED_MODEL_CONFIG_NAME,
    SELECTED_RECONCILIATION_SHIFT_METHOD,
    SELECTED_RECONCILIATION_TOTAL_METHOD,
    SELECTED_YEARLY_SEASONALITY,
    SERIES_LABELS,
    SERIES_TO_SHIFT_ID,
    SHIFT_LABELS,
    SHIFT_SERIES,
    SUPPORTED_HORIZONS,
)
from .data import (  # noqa: F401
    MonthlyAggregates,
    aggregate_monthly,
    add_months,
    latest_observed_month,
    month_span,
    parse_month,
)
from .busiest_shift import (  # noqa: F401
    BusiestShift,
    busiest_shift_hit_rate,
    identify_busiest_shift,
)
from .evaluate import (  # noqa: F401
    DEFAULT_MAX_HORIZON,
    ErrorRow,
    EvaluationSplit,
    Metrics,
    MODEL_LABELS,
    PROPHET_YEARLY_OFF,
    PROPHET_YEARLY_ON,
    SEASONAL_NAIVE,
    busiest_shift_report,
    compare_reconciliation,
    config_for_model,
    filter_rows,
    make_origins,
    make_split,
    model_tag_for_label,
    reconcile_shifts,
    run_evaluation,
    seasonal_naive_predictions,
    select_methods,
    summarize,
    walk_forward,
)
from .pipeline import ForecastDataError, ForecastRunResult, run_forecast_pipeline  # noqa: F401
from .preprocess import (  # noqa: F401
    SeriesData,
    ValidationReport,
    build_all_series,
    build_series,
    contiguous_frontier,
    resolve_window,
    validate_aggregates,
)
from .prophet_model import (  # noqa: F401
    ProphetConfig,
    SeriesForecast,
    fit_and_forecast,
    forecast_all,
    prophet_version,
    selected_config,
)
from .storage import (  # noqa: F401
    busiest_shifts,
    current_forecast_run,
    forecast_run_payload,
    get_forecast_run,
    month_totals,
    persist_forecast_run,
    run_month_map,
)
from .generation import (  # noqa: F401
    GenerationBusy,
    GenerationError,
    GenerationPlan,
    generate_forecast,
    generation_in_progress,
    generation_lock,
    plan_generation,
    publish_generation,
    reusable_evaluation_snapshot,
    validate_generated_run,
    validate_horizon,
)
from .display import (  # noqa: F401
    APP_TIMEZONE,
    TIMEZONE_LABEL,
    crosses_midnight,
    enrich_busiest_shifts,
    format_hours,
    format_timestamp,
    month_name,
    month_range_label,
    shift_catalog_hours,
    shift_display_map,
)
