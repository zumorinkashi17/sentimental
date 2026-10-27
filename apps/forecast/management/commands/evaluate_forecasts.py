"""Chronologically evaluate Prophet against a seasonal-naive baseline.

Usage::

    python manage.py evaluate_forecasts
    python manage.py evaluate_forecasts --start 2020-01 --end 2026-04
    python manage.py evaluate_forecasts --test-months 8 --validation-months 12
    python manage.py evaluate_forecasts --origins 24 --output eval.json

Reads historical data read-only from ``call_session``. Writes nothing to the
database and does not touch any UI or staffing logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.forecast.services import (
    SERIES_LABELS,
    aggregate_monthly,
    build_all_series,
    make_origins,
    make_split,
    resolve_window,
    run_evaluation,
)


class Command(BaseCommand):
    help = "Backtest Prophet monthly call-volume forecasts against a seasonal-naive baseline."

    def add_arguments(self, parser):
        parser.add_argument("--start", default=None, help="First month YYYY-MM (default 2020-01).")
        parser.add_argument("--end", default=None, help="Last month YYYY-MM (default latest contiguous).")
        parser.add_argument("--test-months", type=int, default=8, help="Months held out as the test window.")
        parser.add_argument(
            "--validation-months", type=int, default=12, help="Months held out immediately before the test window."
        )
        parser.add_argument("--origins", type=int, default=24, help="Number of walk-forward forecast origins.")
        parser.add_argument("--max-horizon", type=int, default=12, help="Maximum forecast horizon in months.")
        parser.add_argument("--output", default=None, help="Optional path to write the full report as JSON.")

    def handle(self, *args, **options):
        start, end = resolve_window(options["start"], options["end"])
        if end is None:
            raise CommandError("no historical observations available to evaluate")

        aggregates = aggregate_monthly(start=start, end=end)
        series = build_all_series(aggregates)
        observed = aggregates.present

        try:
            split = make_split(
                observed,
                test_months=options["test_months"],
                validation_months=options["validation_months"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        origins = make_origins(observed, end, options["origins"], options["max_horizon"])
        if not origins:
            raise CommandError("no walk-forward origins available")

        self.stdout.write(self.style.SUCCESS("Evaluation setup"))
        self.stdout.write(f"  window          : {start:%Y-%m} .. {end:%Y-%m}")
        self.stdout.write(f"  validation      : {split.validation_start:%Y-%m} .. {split.validation_end:%Y-%m}")
        self.stdout.write(f"  test            : {split.test_start:%Y-%m} .. {split.test_end:%Y-%m}")
        self.stdout.write(f"  origins         : {len(origins)} ({origins[0]:%Y-%m} .. {origins[-1]:%Y-%m})")
        self.stdout.write(f"  max horizon     : {options['max_horizon']} months")

        report = run_evaluation(series, split, origins, max_horizon=options["max_horizon"])
        selected_model = report.get("selected_model", "prophet_yearly_on")

        for region in ("validation", "test"):
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"{region.capitalize()} — overall metrics"))
            overall_by_model = report[region]["by_model"]
            self.stdout.write(f"  {'model':<20} {'n':>5} {'MAE':>10} {'WAPE %':>10}")
            for model, metrics in sorted(overall_by_model.items()):
                mae = metrics["mae"]
                wape = metrics["wape"]
                self.stdout.write(
                    f"  {model:<20} {metrics['n']:>5} "
                    f"{('-' if mae is None else f'{mae:.2f}'):>10} "
                    f"{('-' if wape is None else f'{wape:.2f}'):>10}"
                )

            self.stdout.write(
                f"  -- {region} by series (selected {selected_model} vs seasonal-naive, WAPE %) --"
            )
            for series_name in ("total", "morning", "afternoon", "night"):
                on = report[region]["by_series"].get(f"{series_name}|{selected_model}", {})
                naive = report[region]["by_series"].get(f"{series_name}|seasonal_naive", {})
                on_w = on.get("wape")
                naive_w = naive.get("wape")
                self.stdout.write(
                    f"    {SERIES_LABELS[series_name]:<18} "
                    f"prophet={('-' if on_w is None else f'{on_w:.2f}'):>8}  "
                    f"naive={('-' if naive_w is None else f'{naive_w:.2f}'):>8}  "
                    f"(n={on.get('n', 0)})"
                )

            self.stdout.write(f"  -- {region} WAPE % by forecast horizon (selected model) --")
            self.stdout.write(
                f"    {'series':<18} {'h1-3':>8} {'h4-6':>8} {'h7-12':>8}"
            )
            for series_name in ("total", "morning", "afternoon", "night"):
                cells = []
                for bucket in ("1-3", "4-6", "7-12"):
                    metrics = report[region]["by_horizon_bucket"].get(
                        f"{series_name}|{selected_model}|h{bucket}"
                    )
                    value = metrics.get("wape") if metrics else None
                    cells.append("-" if value is None else f"{value:.2f}")
                self.stdout.write(
                    f"    {SERIES_LABELS[series_name]:<18} {cells[0]:>8} {cells[1]:>8} {cells[2]:>8}"
                )

        seasonality = report["seasonality"]
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Yearly seasonality test (WAPE %)"))
        self.stdout.write(
            f"  validation: on={seasonality['validation_wape_yearly_on']} "
            f"off={seasonality['validation_wape_yearly_off']}"
        )
        self.stdout.write(
            f"  test      : on={seasonality['test_wape_yearly_on']} "
            f"off={seasonality['test_wape_yearly_off']}"
        )
        self.stdout.write(f"  yearly helps on validation: {seasonality['yearly_helps_on_validation']}")

        reconciliation = report["reconciliation"]
        if reconciliation:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Total: independent forecast vs sum of shifts"))
            for region in ("validation", "test"):
                block = reconciliation.get(region) or {}
                independent = block.get("independent_total") or {}
                summed = block.get("sum_of_shifts") or {}
                residual = block.get("residual_total_minus_shift_sum") or {}
                self.stdout.write(
                    f"  {region:<10} n={block.get('n_cases', 0):>3}  "
                    f"independent MAE={independent.get('mae')} WAPE={independent.get('wape')}  |  "
                    f"sum-of-shifts MAE={summed.get('mae')} WAPE={summed.get('wape')}"
                )
                if residual:
                    self.stdout.write(
                        f"             residual (total - shift sum): mean={residual.get('mean')} "
                        f"mean_abs={residual.get('mean_abs')} max_abs={residual.get('max_abs')}"
                    )
                shift_level = block.get("shift_level") or {}
                raw = (shift_level.get("raw") or {}).get("overall") or {}
                proportional = (shift_level.get("proportional") or {}).get("overall") or {}
                if raw or proportional:
                    self.stdout.write(
                        f"             shift-level WAPE: raw={raw.get('wape')} "
                        f"proportional={proportional.get('wape')}"
                    )

        selection = report.get("selection") or {}
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Selected methods (validation only)"))
        self.stdout.write(f"  config              : {selection.get('config')}")
        self.stdout.write(f"  total reconciliation: {selection.get('total_reconciliation_method')}")
        self.stdout.write(f"  shift reconciliation: {selection.get('shift_reconciliation_method')}")

        future = report.get("future") or {}
        if future:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Future horizon (selected config)"))
            self.stdout.write(
                f"  origin={future['origin']} horizon={future['horizon']} "
                f"config={future['config']} shift-reconciliation={future['shift_reconciliation_method']}"
            )
            total_by_month = {row["month"]: row["yhat"] for row in future["total"]}
            method = future["shift_reconciliation_method"]
            shown = future.get("shifts_reconciled" if method != "raw" else "shifts_raw") or {}
            shift_lookup = {
                name: {row["month"]: row["yhat"] for row in shown.get(name, [])}
                for name in ("morning", "afternoon", "night")
            }
            self.stdout.write(f"  shifts shown with reconciliation={method}")
            for month in sorted(total_by_month):
                parts = " ".join(
                    f"{name}={shift_lookup[name].get(month)}"
                    for name in ("morning", "afternoon", "night")
                )
                self.stdout.write(f"    {month}  total={total_by_month[month]:7.1f}  {parts}")
            for prediction in future.get("busiest_shift", []):
                flag = "  <-- uncertain" if prediction["uncertain"] else ""
                self.stdout.write(
                    f"    busiest {prediction['month']}: {prediction['label']} "
                    f"({prediction['predicted']}) vs {prediction['runner_up']} "
                    f"({prediction['runner_up_predicted']}){flag}"
                )

        busiest = report["busiest_shift"]
        if busiest:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Predicted busiest shift (test window)"))
            self.stdout.write(f"  origin: {busiest['origin']}  model: {busiest.get('model')}")
            for region in ("validation", "test"):
                rates = busiest.get(f"{region}_hit_rate") or {}
                summary = "  ".join(
                    f"{key}={value.get('hit_rate')} (n={value.get('n_cases')})"
                    for key, value in rates.items()
                )
                self.stdout.write(f"  {region} hit rate: {summary}")
            for prediction in busiest["predictions"]:
                flag = "  <-- uncertain" if prediction["uncertain"] else ""
                self.stdout.write(
                    f"    {prediction['month']}  {prediction['label']:<12} "
                    f"yhat={prediction['predicted']:6.1f}  "
                    f"runner-up={prediction['runner_up']} ({prediction['runner_up_predicted']}){flag}"
                )

        if options["output"]:
            path = Path(options["output"])
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"\nWrote report to {path}"))
