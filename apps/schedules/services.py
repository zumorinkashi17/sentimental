"""Staffing-review context for the Shift Schedules & Staffing page.

Reads the *same* persisted forecast run that the Dashboard AI card and the Call
Volume Forecast page use, through the shared read path in
:mod:`apps.forecast.services`. It never trains a model, regenerates a forecast,
queries the forecast tables directly, or touches schedule records.

The result is a **planning aid**: it highlights forecast months whose recorded
shift mix may warrant a staffing review. It deliberately does *not* compute
responder counts or required coverage - service targets, handling time,
utilization and minimum-coverage rules have not been established, so the module
cannot and does not claim to determine exact staffing requirements.
"""

from __future__ import annotations

from datetime import date, datetime

from apps.forecast.services import current_forecast_run, forecast_run_payload


def _month_label(value: str) -> str:
    from apps.forecast.services.display import month_name

    try:
        return month_name(date.fromisoformat(value))
    except (TypeError, ValueError):
        return value


def _day_label(value: str) -> str:
    """Readable timestamp label in the application's timezone."""
    from apps.forecast.services.display import format_timestamp

    return format_timestamp(value)


def staffing_review_context() -> dict:
    """Forecast-backed staffing-review data for the schedules page.

    All values come from the current persisted run. When no run exists the
    context reports ``available=False`` so the page can show an explicit
    unavailable state instead of fabricated recommendations.
    """
    payload = forecast_run_payload(current_forecast_run())
    if not payload.get("available"):
        return {
            "available": False,
            "run_id": None,
            "reason": payload.get("reason") or "No forecast run has been persisted yet.",
            "months": [],
            "review_count": 0,
            "total_months": 0,
            "any_uncertain": False,
            "generated_at": None,
            "generated_label": None,
            "training_start": None,
            "training_end": None,
            "horizon_months": None,
            "model_config_name": None,
            "historical_available_through": None,
            "historical_data_used": None,
            "forecast_period": None,
            "forecast_method": None,
            "stale": False,
            "freshness_notes": [],
        }

    busiest = {item["month"]: item for item in payload.get("busiest_shifts") or []}
    months = []
    review_count = 0
    any_uncertain = False
    for item in payload.get("months") or []:
        lead = busiest.get(item["month"])
        uncertain = bool(lead and lead.get("uncertain"))
        if uncertain:
            review_count += 1
            any_uncertain = True
        months.append(
            {
                "month": item["month"],
                "label": _month_label(item["month"]),
                "total": item["yhat"],
                "total_lower": item["yhat_lower"],
                "total_upper": item["yhat_upper"],
                "leading_shift": (
                    lead.get("display_label") or lead.get("label") if lead else None
                ),
                "leading_predicted": lead.get("predicted") if lead else None,
                "leading_lower": lead.get("lower") if lead else None,
                "leading_upper": lead.get("upper") if lead else None,
                "runner_up": lead.get("runner_up") if lead else None,
                "uncertain": uncertain,
                "reason": lead.get("reason") if lead else None,
                # Every forecast month is a review candidate; uncertainty is
                # reported separately so it is never mistaken for certainty.
                "review": True,
            }
        )

    return {
        "available": True,
        "run_id": payload.get("run_id"),
        "reason": None,
        "months": months,
        "review_count": review_count,
        "total_months": len(months),
        "any_uncertain": any_uncertain,
        "generated_at": payload.get("generated_at"),
        "generated_label": _day_label(payload.get("generated_at")),
        "training_start": payload.get("training_start"),
        "training_end": payload.get("training_end"),
        "horizon_months": payload.get("horizon_months"),
        "model_config_name": payload.get("model_config_name"),
        # Plain-language labels so the page reads like the forecast page.
        "historical_available_through": payload.get("historical_available_through"),
        "historical_data_used": payload.get("historical_data_used"),
        "forecast_period": payload.get("forecast_period"),
        "forecast_method": payload.get("forecast_method"),
        # A run whose forecast window has already elapsed must not be read as a
        # current future forecast, so the page says so explicitly.
        "stale": bool((payload.get("freshness") or {}).get("is_stale")),
        "freshness_notes": (payload.get("freshness") or {}).get("notes") or [],
    }
