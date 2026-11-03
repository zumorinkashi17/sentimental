"""Generate monthly call-volume forecasts for all four series.

Usage::

    python manage.py generate_forecasts                 # 6-month horizon
    python manage.py generate_forecasts --horizon 3
    python manage.py generate_forecasts --start 2020-01 --end 2026-04
    python manage.py generate_forecasts --model yearly_on
    python manage.py generate_forecasts --output forecast.json

Reads historical data read-only from ``call_session``. It does not write to
the database; use ``persist_forecasts`` for the persisted Phase 4 run. Source
rows are never modified.

Default model is the user-approved Phase 3 configuration (yearly seasonality
OFF). Use ``--model yearly_on`` to force the alternative variant.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.forecast.services import (
    ForecastDataError,
    SERIES_LABELS,
    SUPPORTED_HORIZONS,
    ProphetConfig,
    run_forecast_pipeline,
)


class Command(BaseCommand):
    help = "Fit Prophet models on historical monthly call volume and forecast future months."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            default=None,
            help='First training month as YYYY-MM (default: 2020-01).',
        )
        parser.add_argument(
            "--end",
            default=None,
            help='Last training month as YYYY-MM (default: latest contiguous month).',
        )
        parser.add_argument(
            "--horizon",
            type=int,
            default=6,
            help=f"Months to forecast. Supported: {SUPPORTED_HORIZONS} (any positive int accepted).",
        )
        parser.add_argument(
            "--model",
            choices=("yearly_off", "yearly_on"),
            default="yearly_off",
            help="Prophet variant; default is the approved selection (yearly_off).",
        )
        parser.add_argument(
            "--output",
            default=None,
            help="Optional path to write the full forecast payload as JSON.",
        )

    def handle(self, *args, **options):
        horizon = options["horizon"]
        if horizon < 1:
            raise CommandError("--horizon must be a positive integer")

        config = ProphetConfig(yearly_seasonality=(options["model"] == "yearly_on"))

        try:
            result = run_forecast_pipeline(
                start=options["start"],
                end=options["end"],
                horizon=horizon,
                config=config,
            )
        except ForecastDataError as exc:
            self.stdout.write(self.style.ERROR("Validation failed"))
            self.stdout.write(exc.validation.summary())
            for issue in exc.validation.issues:
                self.stdout.write(f"  - {issue}")
            raise CommandError("Refusing to generate forecasts from invalid data.") from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        validation = result.validation
        self.stdout.write(self.style.SUCCESS("Validation"))
        self.stdout.write(validation.summary())

        for month in validation.missing_months:
            self.stdout.write(f"  missing: {month:%Y-%m}")
        for month, count in validation.unknown_shift_months.items():
            self.stdout.write(f"  unmapped shift_id in {month:%Y-%m}: {count} call(s)")
        for name, months in validation.zero_shift_months.items():
            if months:
                self.stdout.write(
                    f"  {SERIES_LABELS[name]} zero month(s): "
                    + ", ".join(f"{m:%Y-%m}" for m in months)
                )

        if not validation.is_valid:
            raise CommandError("Validation failed; refusing to generate forecasts.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Forecast"))
        for name in ("total", "morning", "afternoon", "night"):
            forecast = result.forecasts[name]
            self.stdout.write(f"  {SERIES_LABELS[name]} (trained through {forecast.last_observed:%Y-%m}):")
            for row in forecast.frame.itertuples(index=False):
                self.stdout.write(
                    f"    {row.ds:%Y-%m}  yhat={row.yhat:8.1f}  "
                    f"[{row.yhat_lower:.1f}, {row.yhat_upper:.1f}]"
                )
            self.stdout.write("")

        if options["output"]:
            path = Path(options["output"])
            path.write_text(json.dumps(result.to_payload(), indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote payload to {path}"))
