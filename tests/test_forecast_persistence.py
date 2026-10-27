"""Tests for Phase 4 persistence of forecast runs (models + storage read path)."""

from datetime import date, datetime, timezone
from io import StringIO
from unittest import mock

import pandas as pd
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase

from apps.forecast.models import ForecastRun, ForecastRunMonth
from apps.forecast.services import storage
from apps.forecast.services.pipeline import ForecastDataError, ForecastRunResult
from apps.forecast.services.preprocess import ValidationReport
from apps.forecast.services.prophet_model import SeriesForecast


MONTHS = [date(2026, 5, 1), date(2026, 6, 1)]
SERIES_VALUES = {
    "total": [200.0, 220.0],
    "morning": [100.0, 105.0],
    "afternoon": [70.0, 75.0],
    "night": [25.0, 30.0],
}


def make_series_forecast(name, months, values, width=5.0):
    frame = pd.DataFrame(
        {
            "ds": pd.to_datetime(months),
            "yhat": values,
            "yhat_lower": [v - width for v in values],
            "yhat_upper": [v + width for v in values],
        }
    )
    return SeriesForecast(
        series=name,
        last_observed=date(2026, 4, 1),
        horizon=len(months),
        frame=frame,
        config={"yearly_seasonality": False},
        prophet_version="1.5.0",
    )


def make_result(months=None, values=None, start=None, end=None, generated=None):
    months = months or MONTHS
    values = values or SERIES_VALUES
    forecasts = {
        name: make_series_forecast(name, months, vals) for name, vals in values.items()
    }
    validation = ValidationReport(start=start or date(2020, 1, 1), end=end or date(2026, 4, 1))
    return ForecastRunResult(
        start=start or date(2020, 1, 1),
        end=end or date(2026, 4, 1),
        horizon=len(months),
        aggregates=None,
        validation=validation,
        series={},
        forecasts=forecasts,
        generated_at=generated or datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )


def persist(result=None, **kwargs):
    kwargs.setdefault("model_config_name", "yearly_off")
    kwargs.setdefault("yearly_seasonality", False)
    return storage.persist_forecast_run(result or make_result(), **kwargs)


class PersistRunTests(TestCase):
    def test_persist_creates_run_and_all_series_rows(self):
        run = persist()
        self.assertEqual(run.horizon_months, 2)
        self.assertEqual(run.months.count(), 4 * 2)
        self.assertEqual(
            set(run.months.values_list("series", flat=True)),
            {"total", "morning", "afternoon", "night"},
        )

    def test_months_are_stored_at_month_granularity(self):
        run = persist()
        self.assertEqual(
            sorted(set(run.months.values_list("month", flat=True))),
            [date(2026, 5, 1), date(2026, 6, 1)],
        )
        for month in run.months.values_list("month", flat=True):
            self.assertEqual(month.day, 1)

    def test_run_metadata_is_recorded(self):
        run = persist()
        self.assertEqual(run.model_config_name, "yearly_off")
        self.assertFalse(run.yearly_seasonality)
        self.assertEqual(run.prophet_version, "1.5.0")
        self.assertEqual(run.training_end, date(2026, 4, 1))
        self.assertEqual(run.reconciliation_total_method, "independent_total")
        self.assertEqual(run.reconciliation_shift_method, "raw")
        self.assertEqual(run.model_config, {"yearly_seasonality": False})

    def test_residual_stored_on_total_rows_only(self):
        run = persist()
        for month in MONTHS:
            total = run.months.get(run=run, month=month, series="total")
            shift_sum = sum(
                run.months.get(run=run, month=month, series=name).yhat
                for name in ("morning", "afternoon", "night")
            )
            self.assertAlmostEqual(total.residual_total_minus_shift_sum, total.yhat - shift_sum)
        for name in ("morning", "afternoon", "night"):
            rows = run.months.filter(series=name)
            self.assertTrue(all(r.residual_total_minus_shift_sum is None for r in rows))

    def test_no_series_uses_a_shift_id_two(self):
        # Only the four canonical series exist; shift 2 is not a valid series.
        run = persist()
        choices = dict(ForecastRunMonth._meta.get_field("series").choices)
        self.assertNotIn("2", choices)
        self.assertEqual(set(choices), {"total", "morning", "afternoon", "night"})

    def test_unique_constraint_blocks_duplicate_month_series(self):
        run = persist()
        with self.assertRaises(IntegrityError):
            ForecastRunMonth.objects.create(
                run=run, month=MONTHS[0], series="total", yhat=1.0
            )


class CurrentRunTests(TestCase):
    def test_first_run_is_current(self):
        run = persist()
        self.assertTrue(run.is_current)
        self.assertEqual(storage.current_forecast_run(), run)

    def test_new_run_moves_pointer_without_deleting_prior_run(self):
        first = persist()
        second = persist(result=make_result(values={
            "total": [300.0, 320.0],
            "morning": [150.0, 155.0],
            "afternoon": [90.0, 95.0],
            "night": [40.0, 45.0],
        }))
        self.assertFalse(ForecastRun.objects.get(pk=first.pk).is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(storage.current_forecast_run(), second)
        # Prior run and its rows are retained untouched.
        self.assertTrue(ForecastRunMonth.objects.filter(run=first).exists())
        self.assertEqual(ForecastRun.objects.count(), 2)

    def test_no_current_run_returns_none(self):
        persist(is_current=False)
        self.assertIsNone(storage.current_forecast_run())

    def test_make_current_clears_others(self):
        first = persist()
        second = persist(is_current=False)
        second.make_current()
        self.assertFalse(ForecastRun.objects.get(pk=first.pk).is_current)
        self.assertTrue(ForecastRun.objects.get(pk=second.pk).is_current)


class ReadPathTests(TestCase):
    def test_month_totals_are_rounded_and_ordered(self):
        run = persist()
        totals = storage.month_totals(run)
        self.assertEqual([t["month"] for t in totals], ["2026-05-01", "2026-06-01"])
        self.assertEqual(totals[0]["yhat"], 200.0)
        self.assertIn("residual_total_minus_shift_sum", totals[0])

    def test_run_month_map_covers_every_series(self):
        run = persist()
        data = storage.run_month_map(run)
        self.assertEqual(set(data), {"total", "morning", "afternoon", "night"})
        self.assertEqual(data["total"][MONTHS[1]]["yhat"], 220.0)

    def test_busiest_shifts_flags_uncertain_when_intervals_overlap(self):
        # Top two shifts sit close together -> overlapping intervals -> provisional.
        values = {
            "total": [200.0, 220.0],
            "morning": [100.0, 105.0],
            "afternoon": [98.0, 102.0],
            "night": [25.0, 30.0],
        }
        run = persist(make_result(values=values))
        flagged = storage.busiest_shifts(run)
        self.assertEqual(len(flagged), 2)
        self.assertTrue(all(item["uncertain"] for item in flagged))
        self.assertTrue(all(item["intervals_overlap"] for item in flagged))
        self.assertTrue(all("reason" in item for item in flagged))

    def test_busiest_shifts_certain_when_gap_is_clear(self):
        values = {
            "total": [300.0, 320.0],
            "morning": [200.0, 210.0],
            "afternoon": [50.0, 52.0],
            "night": [20.0, 21.0],
        }
        result = make_result(values=values)
        for name, fc in result.forecasts.items():
            spread = 2.0
            fc.frame["yhat_lower"] = fc.frame["yhat"] - spread
            fc.frame["yhat_upper"] = fc.frame["yhat"] + spread
        run = persist(result)
        flagged = storage.busiest_shifts(run)
        self.assertTrue(all(not item["uncertain"] for item in flagged))
        self.assertTrue(all(item["shift"] == "morning" for item in flagged))

    def test_payload_unavailable_without_run(self):
        payload = storage.forecast_run_payload(None)
        self.assertFalse(payload["available"])
        self.assertIn("reason", payload)

    def test_payload_exposes_config_and_evaluation_snapshot(self):
        run = persist(evaluation_snapshot={"selected_model": "prophet_yearly_off", "split": {"test_start": "2025-09-01"}})
        payload = storage.forecast_run_payload(run)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["model_config_name"], "yearly_off")
        self.assertEqual(payload["evaluation"]["selected_model"], "prophet_yearly_off")
        self.assertIn("September", payload["evaluation"]["note"])
        self.assertTrue(payload["caveats"])


class PersistCommandTests(TestCase):
    def test_command_refuses_invalid_data(self):
        validation = ValidationReport(start=date(2020, 1, 1), end=date(2026, 4, 1))
        validation.issues.append("negative count")
        with mock.patch(
            "apps.forecast.management.commands.persist_forecasts.run_forecast_pipeline",
            side_effect=ForecastDataError(validation),
        ), mock.patch(
            "apps.forecast.management.commands.persist_forecasts.run_evaluation",
            return_value={},
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "persist_forecasts", "--skip-evaluation", "--horizon", "2", stdout=StringIO()
                )
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_command_persists_and_marks_current(self):
        result = make_result()
        with mock.patch(
            "apps.forecast.management.commands.persist_forecasts.run_forecast_pipeline",
            return_value=result,
        ):
            call_command(
                "persist_forecasts", "--skip-evaluation", "--horizon", "2", stdout=StringIO()
            )

        run = storage.current_forecast_run()
        self.assertIsNotNone(run)
        self.assertEqual(run.model_config_name, "yearly_off")
        self.assertFalse(run.yearly_seasonality)
        self.assertEqual(run.months.count(), 8)

    def test_command_no_current_flag_keeps_pointer_empty(self):
        with mock.patch(
            "apps.forecast.management.commands.persist_forecasts.run_forecast_pipeline",
            return_value=make_result(),
        ):
            call_command(
                "persist_forecasts",
                "--skip-evaluation",
                "--no-current",
                "--horizon",
                "2",
                stdout=StringIO(),
            )
        self.assertIsNone(storage.current_forecast_run())
        self.assertEqual(ForecastRun.objects.count(), 1)
