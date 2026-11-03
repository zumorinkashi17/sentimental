"""Staffing-review context for the Shift Schedules & Staffing page.

Reads the *same* persisted forecast run that the Dashboard AI card and the Call
Volume Forecast page use, through the shared read path in
:mod:`apps.forecast.services`. It never trains a model, regenerates a forecast,
queries the forecast tables directly, or touches schedule records.

The result is a **planning aid**: it highlights forecast months whose recorded
shift mix may warrant a staffing review and now also includes monthly
staffing estimates derived from the persisted forecast plus administrator-
configured AHT and staffing assumptions.
"""

from __future__ import annotations

from datetime import date, datetime

from apps.forecast.services import current_forecast_run, forecast_run_payload
from apps.schedules.staffing_service import calculate_staffing, ceil_value
from apps.schedules.models import ShiftSchedule
from apps.forecast.services.display import shift_catalog_hours
from collections import defaultdict


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

    Additionally merges the staffing calculation results from
    :func:`apps.staffing.services.calculate_staffing`, so the page can render
    summary cards, a monthly staffing table, and a shift comparison.
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
            # Staffing keys when unavailable.
            "staffing_available": False,
            "staffing_months": [],
            "staffing_totals": {},
            "staffing_aht_used": {},
            "staffing_assumptions_used": {},
            "staffing_reason": "No forecast run has been persisted yet.",
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

    # Staffing calculation from the same persisted run.
    # Wrapped defensively so a staffing issue never breaks the schedules page.
    staffing_available = False
    staffing_months = []
    staffing_totals = {}
    staffing_aht_used = {}
    staffing_assumptions_used = {}
    staffing_reason = "Staffing calculation unavailable."
    staffing_run_id = None
    staffing_run_generated_at = None
    staffing_calculation_timestamp = None
    staffing_config_version = None
    try:
        staffing_result = calculate_staffing(current_forecast_run())
        if staffing_result.available:
            staffing_available = True
            staffing_months = staffing_result.months
            staffing_totals = staffing_result.totals
            staffing_aht_used = staffing_result.aht_used
            staffing_assumptions_used = staffing_result.assumptions_used
            staffing_reason = staffing_result.reason or ""
            staffing_run_id = staffing_result.run_id
            staffing_run_generated_at = staffing_result.run_generated_at
            staffing_calculation_timestamp = staffing_result.calculation_timestamp
            staffing_config_version = staffing_result.config_version
        else:
            staffing_reason = staffing_result.reason or "Staffing calculation unavailable."
    except Exception:
        staffing_available = False
        staffing_reason = "Staffing calculation encountered an error."

    # Enrich staffing months with scheduled staff counts, diffs, and statuses.
    shifts_requiring_review = 0
    staffing_by_shift = {}
    if staffing_available and staffing_months:
        scheduled_counts = _scheduled_staff_by_shift_month()
        for m in staffing_months:
            for shift in m["shifts"]:
                series = shift["series"]
                recommended = shift["recommended_staff"]
                if series not in staffing_by_shift:
                    staffing_by_shift[series] = {
                        "series": series,
                        "shift_name": shift["shift_name"],
                        "shift_hours": shift["shift_hours"],
                        "recommended_staff": recommended,
                    }
                else:
                    if recommended > staffing_by_shift[series]["recommended_staff"]:
                        staffing_by_shift[series]["recommended_staff"] = recommended

                diff_key = series + "|" + m["month"]
                scheduled_count = scheduled_counts.get(diff_key, 0)
                diff = recommended - scheduled_count
                if diff > 0:
                    status = "Below Recommendation"
                    status_class = "red"
                    shifts_requiring_review += 1
                elif diff < 0:
                    status = "Above Recommendation"
                    status_class = "emerald"
                else:
                    status = "Meets Recommendation"
                    status_class = "gray"
                shift["scheduled_count"] = scheduled_count
                shift["diff"] = diff
                shift["status"] = status
                shift["status_class"] = status_class
        staffing_totals["shifts_requiring_review"] = shifts_requiring_review
        staffing_totals["total_recommended_staff"] = sum(
            s["recommended_staff"] for s in staffing_by_shift.values()
        )

    # Merge recommended staff per month into the review-month cards so the
    # Staffing Review cards show forecast calls + recommended staff together.
    staffing_month_lookup = {}
    if staffing_available:
        for m in staffing_months:
            staffing_month_lookup[m["month"]] = {
                "total_recommended_staff": m.get("total_recommended_staff"),
                "shifts": [
                    {
                        "series": s["series"],
                        "shift_name": s["shift_name"],
                        "shift_hours": s["shift_hours"],
                        "recommended_staff": s["recommended_staff"],
                    }
                    for s in m.get("shifts", [])
                ],
            }
    for m in months:
        m["total_recommended_staff"] = (
            staffing_month_lookup.get(m["month"], {}).get("total_recommended_staff")
        )
        m["shift_staff"] = staffing_month_lookup.get(m["month"], {}).get("shifts", [])

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
        # Staffing results.
        "staffing_available": staffing_available,
        "staffing_months": staffing_months,
        "staffing_totals": staffing_totals,
        "staffing_aht_used": staffing_aht_used,
        "staffing_assumptions_used": staffing_assumptions_used,
        "staffing_reason": staffing_reason,
        "staffing_run_id": staffing_run_id,
        "staffing_run_generated_at": staffing_run_generated_at,
        "staffing_calculation_timestamp": staffing_calculation_timestamp,
        "staffing_config_version": staffing_config_version,
    }


def _scheduled_staff_by_shift_month() -> dict:
    """Return currently scheduled staff counts grouped by shift series and month.

    Keys are ``"series|YYYY-MM"`` strings mapping to distinct scheduled user
    counts for ``schedule_status='Scheduled'``. Shift series is inferred from
    the ShiftCatalog working hours.
    """
    catalog = shift_catalog_hours()
    shift_id_to_series = {}
    for shift_id, entry in catalog.items():
        start = entry["start"]
        end = entry["end"]
        if start.hour == 6 and end.hour == 14:
            shift_id_to_series[shift_id] = "morning"
        elif start.hour == 14 and end.hour == 22:
            shift_id_to_series[shift_id] = "afternoon"
        elif start.hour == 22 and end.hour == 6:
            shift_id_to_series[shift_id] = "night"

    result = defaultdict(int)
    schedules = ShiftSchedule.objects.filter(
        schedule_status='Scheduled'
    ).select_related('shift')
    for sched in schedules:
        series = shift_id_to_series.get(sched.shift_id)
        if series is None or sched.shift_date is None:
            continue
        key = series + "|" + sched.shift_date.strftime("%Y-%m")
        result[key] += 1
    return dict(result)
