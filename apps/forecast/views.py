"""Call Volume Forecast page, its data export and the Generate Forecast action.

The page and the export read the *same* current persisted forecast run
through :mod:`apps.forecast.services.storage`. Nothing here retrains a model,
touches ``call_session`` history, or re-implements forecasting; the page is a
pure view over the stored run so the numbers on screen and the exported file
always agree.

The only action that creates a run is the ``generate`` endpoint. It reuses the
existing pipeline through :mod:`apps.forecast.services.generation` and
publishes the new run as current only after generation *and* validation
succeed - a failed attempt leaves the previous run current and writes nothing.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date
from urllib.parse import urlencode

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.models import User
from apps.forecast.services import (
    DEFAULT_FORECAST_HORIZON,
    SERIES_LABELS,
    SERIES_TO_SHIFT_ID,
    SHIFT_SERIES,
    SUPPORTED_HORIZONS,
    current_forecast_run,
    forecast_run_payload,
    run_month_map,
)
from apps.forecast.services.generation import (
    GenerationBusy,
    GenerationError,
    generate_forecast,
    generation_lock,
    publish_generation,
    reusable_evaluation_snapshot,
    validate_horizon,
)
from apps.forecast.services.pipeline import ForecastDataError

logger = logging.getLogger(__name__)

MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

# Column order used by both the table and the CSV export.
EXPORT_SERIES_ORDER = ("total",) + SHIFT_SERIES

# Name/value carried by the Generate Forecast button. A submit button's
# name/value is only sent when that button activated the form, so an
# implicit submission (for example pressing Enter in the horizon selector)
# can be told apart from an explicit click and refused.
GENERATION_ACTION = "generate"


def _resolve_admin(request):
    """Return ``(user, reason)``; ``reason`` is ``None`` for an active admin.

    ``reason`` is one of ``anonymous``, ``inactive`` or ``not_admin`` so the
    JSON endpoint can answer with a status code instead of a redirect.
    """
    if not hasattr(request, "_sentimental_user"):
        user_id = request.session.get("user_id")
        if not user_id:
            return None, "anonymous"
        try:
            request._sentimental_user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            request.session.flush()
            return None, "anonymous"

    user = request._sentimental_user
    if user.user_status != User.StatusChoices.ACTIVE:
        request.session.flush()
        return None, "inactive"
    if user.user_role != User.RoleChoices.ADMIN:
        return None, "not_admin"
    return user, None


def _get_admin(request):
    """Return ``(user, redirect_response)`` for an active admin, else redirect."""
    user, reason = _resolve_admin(request)
    if reason in ("anonymous", "inactive"):
        return None, redirect("accounts:login")
    if reason == "not_admin":
        return None, redirect("dashboard:index")
    return user, None


def _month_label(month: date) -> str:
    return f"{MONTH_ABBR[month.month - 1]} {month.year}"


def _series_label(name: str, shift_labels: dict) -> str:
    """User-facing label for a series: no internal shift id is exposed."""
    if name == "total":
        return "Total calls (all shifts)"
    info = shift_labels.get(name)
    return info["label"] if info else SERIES_LABELS.get(name, name)


def build_forecast_page_context(run) -> dict:
    """Turn one persisted run into the rows/JSON the template renders.

    Uses only the storage read helpers so the display can never drift from the
    persisted values.
    """
    payload = forecast_run_payload(run)
    if not payload.get("available"):
        return {
            "forecast": payload,
            "forecast_available": False,
            "horizon_options": SUPPORTED_HORIZONS,
            "default_horizon": DEFAULT_FORECAST_HORIZON,
        }
    data = run_month_map(run)
    months = sorted(data["total"])
    shift_labels = payload.get("shift_labels") or {}

    # Aligned matrix: one row per series, one cell per month, in the same order
    # as ``month_labels`` so the template renders without dynamic dict lookups.
    month_labels = [_month_label(m) for m in months]
    display_rows = []
    for name in EXPORT_SERIES_ORDER:
        cells = []
        for month in months:
            point = data[name].get(month)
            cells.append(
                None
                if point is None
                else {
                    "yhat": point["yhat"],
                    "yhat_lower": point["yhat_lower"],
                    "yhat_upper": point["yhat_upper"],
                    "residual": point["residual_total_minus_shift_sum"],
                }
            )
        display_rows.append(
            {
                "key": name,
                "label": _series_label(name, shift_labels),
                "cells": cells,
            }
        )

    def series_json(name):
        return json.dumps(
            [
                None if data[name].get(m) is None else round(data[name][m]["yhat"], 1)
                for m in months
            ]
        )

    def bound_json(name, key):
        return json.dumps(
            [
                None if data[name].get(m) is None or data[name][m][key] is None
                else round(data[name][m][key], 1)
                for m in months
            ]
        )

    uncertain_months = sum(1 for item in payload["busiest_shifts"] if item["uncertain"])

    busiest_by_month = {item["month"]: item for item in payload["busiest_shifts"]}
    busiest_row = [
        busiest_by_month.get(month.isoformat()) for month in months
    ]

    return {
        "forecast": payload,
        "forecast_available": True,
        "display_rows": display_rows,
        "month_labels": month_labels,
        "busiest_row": busiest_row,
        "any_busiest_uncertain": any(
            item and item.get("uncertain") for item in busiest_row
        ),
        "chart": {
            "months": json.dumps(month_labels),
            "total": series_json("total"),
            "total_lower": bound_json("total", "yhat_lower"),
            "total_upper": bound_json("total", "yhat_upper"),
        },
        "uncertain_months": uncertain_months,
        "total_months": len(months),
        "horizon_months": payload["horizon_months"],
        "horizon_options": SUPPORTED_HORIZONS,
        # The selector keeps showing the published run's horizon when it is one
        # of the supported values, so opening the page never suggests a
        # different forecast than the one that is published.
        "default_horizon": (
            payload["horizon_months"]
            if payload["horizon_months"] in SUPPORTED_HORIZONS
            else DEFAULT_FORECAST_HORIZON
        ),
        "generated_at": payload["generated_at"],
        "generated_display": payload["generated_display"],
        "training_start": payload["training_start"],
        "training_end": payload["training_end"],
        "model_config_name": payload["model_config_name"],
        # Plain-language labels for the three pages.
        "shift_labels": payload.get("shift_labels") or {},
        "historical_available_through": payload["historical_available_through"],
        "historical_data_used": payload["historical_data_used"],
        "forecast_period": payload["forecast_period"],
        "forecast_method": payload["forecast_method"],
        "missing_data_action": (payload.get("freshness") or {}).get("action"),
        "missing_range_label": (payload.get("freshness") or {}).get("missing_range_label"),
        "notes": list(payload.get("caveats") or [])
        + ([payload["evaluation"]["note"]] if payload.get("evaluation") else []),
    }


def prediction(request):
    """Render the Call Volume Forecast page from the current persisted run."""
    user, redirect_response = _get_admin(request)
    if redirect_response:
        return redirect_response

    run = current_forecast_run()
    context = build_forecast_page_context(run)
    context["current_forecast_run"] = run
    context["generation_notice"] = _generation_notice(request)
    return render(request, "forecast/prediction.html", context)


def _wants_json(request) -> bool:
    """Whether the caller expects a JSON body instead of a page.

    AJAX/API clients (``X-Requested-With: XMLHttpRequest`` or a JSON-only
    ``Accept`` header) keep the JSON contract; a plain browser form post is
    answered with a redirect back to the Call Volume Forecast page.
    """
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _forecast_page_url(**params) -> str:
    """URL of the Call Volume Forecast page with a result message attached."""
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    query = urlencode(clean)
    base = reverse("forecast:prediction")
    return f"{base}?{query}" if query else base


def _generation_response(request, payload: dict, status: int):
    """Answer a generation request the way the caller expects.

    JSON clients get the JSON body; a browser form post is redirected back to
    the Call Volume Forecast page, which then shows the success or error
    message. A raw JSON body is never rendered in the browser.
    """
    if _wants_json(request):
        return JsonResponse(payload, status=status)

    if payload.get("ok"):
        target = _forecast_page_url(
            generated=payload.get("run_id"),
            horizon=payload.get("horizon"),
            start=payload.get("forecast_start"),
            end=payload.get("forecast_end"),
        )
    else:
        message = (payload.get("error") or "Forecast generation failed.")[:240]
        target = _forecast_page_url(generation_error=message)

    response = redirect(target)
    response.status_code = 303  # POST -> GET, so the form is never re-posted
    return response


def _generation_notice(request) -> dict:
    """The success/error message the page shows after a generation attempt."""
    run_id = request.GET.get("generated")
    if run_id:
        horizon = request.GET.get("horizon")
        start = request.GET.get("start")
        end = request.GET.get("end")
        window = ""
        try:
            if start and end:
                window = (
                    f" ({_month_label(date.fromisoformat(start))} to "
                    f"{_month_label(date.fromisoformat(end))})"
                )
        except ValueError:
            window = ""
        span = f"{horizon} month(s)" if horizon else "the requested number of months"
        return {
            "level": "success",
            "title": "Forecast published",
            "text": (
                f"Run {run_id} is now the current forecast for {span}{window}. "
                "The Call Volume Forecast page, the Manager Dashboard and the "
                "Schedule page all show this same run."
            ),
        }

    error = request.GET.get("generation_error")
    if error:
        return {
            "level": "error",
            "title": "Forecast not generated",
            "text": (
                f"{error} The previously published forecast is unchanged and "
                "remains current."
            ),
        }
    return {}


def generate(request):
    """Generate a new forecast run for the selected horizon (admin only).

    The horizon must be one of 3, 6 or 12 months and the request must carry
    the explicit ``action=generate`` marker sent by the Generate Forecast
    button, so changing the selector never generates anything by itself.

    The run is published as the current run only after generation *and*
    validation succeed; on any failure nothing is written and the previous run
    stays current. Browser form posts are redirected back to the Call Volume
    Forecast page with the result; AJAX/API clients receive JSON.
    """
    wants_json = _wants_json(request)

    user, reason = _resolve_admin(request)
    if reason in ("anonymous", "inactive"):
        if wants_json:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Your session has expired. Sign in again to generate a forecast.",
                },
                status=401,
            )
        return redirect("accounts:login")
    if reason == "not_admin":
        if wants_json:
            return JsonResponse(
                {"ok": False, "error": "Only administrators can generate a forecast."},
                status=403,
            )
        return redirect("dashboard:index")
    if request.method != "POST":
        if wants_json:
            return JsonResponse(
                {"ok": False, "error": "Use POST to generate a forecast."}, status=405
            )
        return redirect("forecast:prediction")

    if request.POST.get("action") != GENERATION_ACTION:
        return _generation_response(
            request,
            {
                "ok": False,
                "error": (
                    "Generating a forecast requires an explicit request. Use the "
                    "Generate Forecast button."
                ),
            },
            status=400,
        )

    try:
        horizon = validate_horizon(request.POST.get("horizon"))
    except GenerationError as exc:
        return _generation_response(request, {"ok": False, "error": str(exc)}, status=400)

    try:
        with generation_lock():
            result, plan = generate_forecast(horizon)
            run = publish_generation(
                result, plan, evaluation_snapshot=reusable_evaluation_snapshot()
            )
    except GenerationBusy as exc:
        return _generation_response(request, {"ok": False, "error": str(exc)}, status=409)
    except ForecastDataError as exc:
        return _generation_response(
            request,
            {
                "ok": False,
                "error": (
                    "The historical data failed validation, so no forecast was "
                    "generated. " + exc.validation.summary()
                ),
            },
            status=422,
        )
    except GenerationError as exc:
        # Generation or publication refused the run (for example the generated
        # months did not match the requested horizon).
        return _generation_response(request, {"ok": False, "error": str(exc)}, status=422)
    except ValueError as exc:
        return _generation_response(
            request,
            {
                "ok": False,
                "error": (
                    "The historical data could not be used for a forecast, so "
                    f"nothing was generated. {exc}"
                ),
            },
            status=422,
        )
    except Exception:
        logger.exception("Forecast generation failed")
        return _generation_response(
            request,
            {
                "ok": False,
                "error": (
                    "Forecast generation failed unexpectedly. The previous "
                    "forecast is unchanged."
                ),
            },
            status=500,
        )

    months = plan.published_months
    return _generation_response(
        request,
        {
            "ok": True,
            "run_id": run.run_id,
            "horizon": plan.horizon,
            "forecast_start": plan.forecast_start.isoformat(),
            "forecast_end": plan.forecast_end.isoformat(),
            "months": [month.isoformat() for month in months],
            "message": (
                f"Forecast published for {len(months)} month(s): "
                f"{plan.forecast_start:%B %Y} to {plan.forecast_end:%B %Y}."
            ),
        },
        status=200,
    )


def export(request):
    """Export exactly the persisted forecast currently shown on the page.

    Format is chosen with ``?format=csv`` (default) or ``?format=json``; either
    way the values come from the same storage read helpers as the page.
    """
    user, redirect_response = _get_admin(request)
    if redirect_response:
        return redirect_response

    run = current_forecast_run()
    payload = forecast_run_payload(run)
    if not payload.get("available"):
        return JsonResponse(
            {"available": False, "reason": payload.get("reason")}, status=404
        )

    if request.GET.get("format") == "json":
        response = JsonResponse(payload, json_dumps_params={"indent": 2})
        response["Content-Disposition"] = "attachment; filename=call_volume_forecast.json"
        return response

    data = run_month_map(run)
    months = sorted(data["total"])
    shift_labels = payload.get("shift_labels") or {}

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = "attachment; filename=call_volume_forecast.csv"
    writer = csv.writer(response)
    writer.writerow(
        [
            "run_id",
            "generated_at",
            "generated_display",
            "training_start",
            "training_end",
            "horizon_months",
            "model_config",
            "reconciliation_total_method",
            "reconciliation_shift_method",
            "month",
            "series",
            "series_label",
            "shift_id",
            "yhat",
            "yhat_lower",
            "yhat_upper",
            "residual_total_minus_shift_sum",
        ]
    )
    for month in months:
        for name in EXPORT_SERIES_ORDER:
            point = data[name].get(month)
            if point is None:
                continue
            label = shift_labels.get(name, {}).get("label")
            writer.writerow(
                [
                    payload["run_id"],
                    payload["generated_at"],
                    payload.get("generated_display") or "",
                    payload["training_start"],
                    payload["training_end"],
                    payload["horizon_months"],
                    payload["model_config_name"],
                    payload["reconciliation_total_method"],
                    payload["reconciliation_shift_method"],
                    month.isoformat(),
                    name,
                    label or "",
                    SERIES_TO_SHIFT_ID.get(name, ""),
                    round(point["yhat"], 2),
                    "" if point["yhat_lower"] is None else round(point["yhat_lower"], 2),
                    "" if point["yhat_upper"] is None else round(point["yhat_upper"], 2),
                    "" if point["residual_total_minus_shift_sum"] is None
                    else round(point["residual_total_minus_shift_sum"], 2),
                ]
            )
    return response
