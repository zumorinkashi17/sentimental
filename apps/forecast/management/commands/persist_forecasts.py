"""Persist a monthly call-volume forecast run for the application pages.

Usage::

    python manage.py persist_forecasts
    python manage.py persist_forecasts --horizon 6 --config yearly_off
    python manage.py persist_forecasts --evaluation-json evaluation.json
    python manage.py persist_forecasts --no-current       # keep a run without switching pages

By default the run uses the user-approved configuration (yearly seasonality
OFF) and is marked *current*, so the Dashboard / Call Volume Forecast / Shift
Schedules pages all read this one run. Prior runs are never overwritten - only
the single ``is_current`` pointer moves.

The Phase 3 evaluation snapshot is stored alongside the run so the model choice
is auditable. Pass ``--evaluation-json`` to reuse a previous evaluation instead
of recomputing it.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.forecast.services import (
    DEFAULT_FORECAST_HORIZON,
    DEFAULT_MAX_HORIZON,
    ForecastDataError,
    SERIES_LABELS,
    SHIFT_LABELS,
    SUPPORTED_HORIZONS,
    aggregate_monthly,
    build_all_series,
    busiest_shifts,
    config_for_model,
    make_origins,
    make_split,
    parse_month,
    persist_forecast_run,
    resolve_window,
    run_evaluation,
    run_forecast_pipeline,
)
from apps.forecast.services.constants import (
    SELECTED_MODEL_CONFIG_NAME,
    SELECTED_RECONCILIATION_SHIFT_METHOD,
    SELECTED_RECONCILIATION_TOTAL_METHOD,
)

CONFIG_CHOICES = ("auto", "yearly_on", "yearly_off")


class Command(BaseCommand):
    help = "Fit and persist a monthly call-volume forecast run (Phase 4)."

    def add_arguments(self, parser):
        parser.add_argument("--start", default=None, help="First training month YYYY-MM (default 2020-01).")
        parser.add_argument("--end", default=None, help="Last training month YYYY-MM (default: latest contiguous month).")
        parser.add_argument(
            "--horizon",
            type=int,
            default=DEFAULT_FORECAST_HORIZON,
            help=f"Months to persist. Supported: {SUPPORTED_HORIZONS}.",
        )
        parser.add_argument(
            "--config",
            choices=CONFIG_CHOICES,
            default="auto",
            help="'auto' (default) uses the Phase 3 selection; otherwise force a variant.",
        )
        parser.add_argument(
            "--evaluation-json",
            default=None,
            help="Reuse a Phase 3 evaluation report (JSON) instead of recomputing it.",
        )
        parser.add_argument(
            "--skip-evaluation",
            action="store_true",
            help="Do not run/store an evaluation snapshot (not recommended; the choice becomes unauditable).",
        )
        parser.add_argument(
            "--evaluation-origins",
            type=int,
            default=DEFAULT_MAX_HORIZON,
            help="Number of walk-forward origins for a freshly computed evaluation.",
        )
        parser.add_argument(
            "--evaluation-months",
            type=int,
            default=8,
            help="Held-out test window length in months for a fresh evaluation.",
        )
        parser.add_argument(
            "--validation-months",
            type=int,
            default=12,
            help="Validation window length in months for a fresh evaluation.",
        )
        parser.add_argument(
            "--no-current",
            action="store_true",
            help="Store the run without making it the current one the pages read.",
        )
        parser.add_argument(
            "--output",
            default=None,
            help="Optional path to also write the persisted run payload as JSON.",
        )

    def handle(self, *args, **options):
        horizon = options["horizon"]
        if horizon < 1:
            raise CommandError("--horizon must be a positive integer")

        evaluation = self._load_or_build_evaluation(options)
        model_tag = self._resolve_model_tag(options["config"], evaluation)

        try:
            result = run_forecast_pipeline(
                start=options["start"],
                end=options["end"],
                horizon=horizon,
                config=config_for_model(model_tag),
            )
        except ForecastDataError as exc:
            self.stdout.write(self.style.ERROR("Validation failed"))
            self.stdout.write(exc.validation.summary())
            for issue in exc.validation.issues:
                self.stdout.write(f"  - {issue}")
            raise CommandError("Refusing to persist forecasts from invalid data.") from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Validation"))
        self.stdout.write(result.validation.summary())
        if not result.validation.is_valid:
            raise CommandError("Validation failed; refusing to persist forecasts.")

        config_name = "yearly_on" if model_tag == "prophet_yearly_on" else "yearly_off"
        total_method = (
            evaluation.get("selection", {}).get("total_reconciliation_method")
            if evaluation
            else None
        ) or SELECTED_RECONCILIATION_TOTAL_METHOD
        shift_method = (
            evaluation.get("selection", {}).get("shift_reconciliation_method")
            if evaluation
            else None
        ) or SELECTED_RECONCILIATION_SHIFT_METHOD

        run = persist_forecast_run(
            result,
            model_config_name=config_name,
            yearly_seasonality=(model_tag == "prophet_yearly_on"),
            reconciliation_total_method=total_method,
            reconciliation_shift_method=shift_method,
            evaluation_snapshot=evaluation or {},
            is_current=not options["no_current"],
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Persisted"))
        self.stdout.write(
            f"  run #{run.run_id}  config={config_name}  "
            f"training {run.training_start:%Y-%m}..{run.training_end:%Y-%m}  "
            f"horizon={run.horizon_months}  current={run.is_current}"
        )
        self.stdout.write(
            f"  reconciliation: total={run.reconciliation_total_method} "
            f"shifts={run.reconciliation_shift_method}"
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Forecast months"))
        for item in run.months.filter(series="total").order_by("month"):
            residual = item.residual_total_minus_shift_sum
            self.stdout.write(
                f"  {item.month:%Y-%m}  total={item.yhat:8.1f}  "
                f"[{item.yhat_lower:.1f}, {item.yhat_upper:.1f}]  "
                f"residual(total-sum)={0.0 if residual is None else residual:+.2f}"
            )

        flagged = [b for b in busiest_shifts(run) if b["uncertain"]]
        self.stdout.write("")
        self.stdout.write(
            f"  busiest-shift months flagged uncertain: {len(flagged)}/{run.horizon_months} "
            f"(provisional; see Shift Schedules)"
        )

        if options["output"]:
            path = Path(options["output"])
            path.write_text(
                json.dumps(self._payload(run, model_tag, evaluation), indent=2, default=str),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"Wrote run payload to {path}"))

    def _resolve_model_tag(self, config: str, evaluation: dict) -> str:
        if config == "yearly_on":
            return "prophet_yearly_on"
        if config == "yearly_off":
            return "prophet_yearly_off"
        selected = (evaluation or {}).get("selected_model")
        if selected in ("prophet_yearly_on", "prophet_yearly_off"):
            return selected
        return f"prophet_{SELECTED_MODEL_CONFIG_NAME}"

    def _load_or_build_evaluation(self, options) -> dict:
        if options["skip_evaluation"]:
            return {"skipped": True, "reason": "--skip-evaluation was passed"}
        if options["evaluation_json"]:
            path = Path(options["evaluation_json"])
            if not path.exists():
                raise CommandError(f"evaluation file not found: {path}")
            return json.loads(path.read_text(encoding="utf-8"))

        explicit_window = bool(options["start"] and options["end"])
        if explicit_window:
            resolved_start = parse_month(options["start"])
            resolved_end = parse_month(options["end"])
        else:
            resolved_start, resolved_end = resolve_window(options["start"], options["end"])
        if resolved_end is None:
            raise CommandError("no historical observations available to evaluate")

        series = build_all_series(aggregate_monthly(start=resolved_start, end=resolved_end))
        split = make_split(series["total"], options["evaluation_months"], options["validation_months"])
        origins = make_origins(series["total"], split, options["evaluation_origins"])
        self.stdout.write(
            f"Running evaluation: {len(origins)} origin(s), "
            f"validation {split.validation_start:%Y-%m}..{split.validation_end:%Y-%m}, "
            f"test {split.test_start:%Y-%m}..{split.test_end:%Y-%m}"
        )
        return run_evaluation(series, split, origins, DEFAULT_MAX_HORIZON)

    def _payload(self, run, model_tag: str, evaluation: dict) -> dict:
        from apps.forecast.services import forecast_run_payload

        payload = forecast_run_payload(run)
        payload["series_labels"] = SERIES_LABELS
        payload["shift_labels"] = {str(k): v for k, v in SHIFT_LABELS.items()}
        payload["requested_model"] = model_tag
        payload["evaluation_available"] = bool(evaluation)
        return payload
