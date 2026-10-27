"""Tests for the Phase 2 forecasting pipeline (data -> validation -> Prophet)."""

from datetime import date, time

from django.test import TestCase

from apps.callers.models import CallSession
from apps.forecast.services import (
    ProphetConfig,
    aggregate_monthly,
    build_series,
    contiguous_frontier,
    fit_and_forecast,
    parse_month,
    resolve_window,
    run_forecast_pipeline,
    validate_aggregates,
)
from apps.forecast.services.data import add_months, month_span
from apps.forecast.services.prophet_model import prophet_version
from apps.schedules.models import ShiftCatalog


def make_canonical_shifts():
    """Create the three shifts with their real database IDs (1, 3, 4)."""
    return {
        1: ShiftCatalog.objects.create(shift_id=1, shift_start_time=time(6, 0), shift_end_time=time(14, 0)),
        3: ShiftCatalog.objects.create(shift_id=3, shift_start_time=time(14, 0), shift_end_time=time(22, 0)),
        4: ShiftCatalog.objects.create(shift_id=4, shift_start_time=time(22, 0), shift_end_time=time(6, 0)),
    }


def add_calls(shift, on, count):
    for _ in range(count):
        CallSession.objects.create(
            caller_id=add_calls.caller_id,
            shift=shift,
            session_call_date=on,
            session_time_called=time(9, 0),
            session_risk_assessment="Low",
            session_summarization="s",
        )


class MonthHelperTests(TestCase):
    def test_parse_month(self):
        self.assertEqual(parse_month("2020-03"), date(2020, 3, 1))

    def test_add_months_wraps_year(self):
        self.assertEqual(add_months(date(2026, 11, 1), 3), date(2027, 2, 1))
        self.assertEqual(add_months(date(2020, 1, 1), -1), date(2019, 12, 1))

    def test_month_span_inclusive(self):
        self.assertEqual(
            month_span(date(2020, 1, 1), date(2020, 4, 1)),
            [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 4, 1)],
        )
        self.assertEqual(month_span(date(2020, 4, 1), date(2020, 1, 1)), [])


class AggregationTests(TestCase):
    def setUp(self):
        from tests.helpers import make_caller

        self.shifts = make_canonical_shifts()
        add_calls.caller_id = make_caller().caller_id

    def test_monthly_totals_and_shift_split(self):
        add_calls(self.shifts[1], date(2020, 1, 5), 3)   # morning
        add_calls(self.shifts[3], date(2020, 1, 9), 2)   # afternoon
        add_calls(self.shifts[4], date(2020, 1, 9), 1)   # night
        add_calls(self.shifts[1], date(2020, 2, 3), 5)   # morning only

        agg = aggregate_monthly(start=date(2020, 1, 1), end=date(2020, 3, 1))

        self.assertEqual(agg.months, [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)])
        self.assertEqual(agg.total[date(2020, 1, 1)], 6)
        self.assertEqual(agg.morning[date(2020, 1, 1)], 3)
        self.assertEqual(agg.afternoon[date(2020, 1, 1)], 2)
        self.assertEqual(agg.night[date(2020, 1, 1)], 1)
        self.assertEqual(agg.total[date(2020, 2, 1)], 5)
        self.assertEqual(agg.afternoon[date(2020, 2, 1)], 0)

    def test_missing_month_is_not_zero_filled(self):
        add_calls(self.shifts[1], date(2020, 1, 5), 4)

        agg = aggregate_monthly(start=date(2020, 1, 1), end=date(2020, 3, 1))

        self.assertEqual(agg.present, [date(2020, 1, 1)])
        self.assertEqual(agg.missing, [date(2020, 2, 1), date(2020, 3, 1)])
        self.assertNotIn(date(2020, 2, 1), agg.total)


class ValidationTests(TestCase):
    def setUp(self):
        from tests.helpers import make_caller

        self.shifts = make_canonical_shifts()
        add_calls.caller_id = make_caller().caller_id

    def test_reconciles_total_against_shifts(self):
        add_calls(self.shifts[1], date(2020, 1, 5), 3)
        add_calls(self.shifts[3], date(2020, 1, 6), 2)
        add_calls(self.shifts[4], date(2020, 1, 7), 1)

        report = validate_aggregates(aggregate_monthly(date(2020, 1, 1), date(2020, 1, 1)))

        self.assertEqual(report.reconciliation_failures, [])
        self.assertTrue(report.is_valid)

    def test_unmapped_shift_is_a_blocking_issue(self):
        # shift_id 2 does not exist in the verified mapping.
        stray = ShiftCatalog.objects.create(
            shift_id=2, shift_start_time=time(0, 0), shift_end_time=time(8, 0)
        )
        add_calls(self.shifts[1], date(2020, 1, 5), 2)
        add_calls(stray, date(2020, 1, 6), 1)

        agg = aggregate_monthly(date(2020, 1, 1), date(2020, 1, 1))
        report = validate_aggregates(agg)

        self.assertEqual(agg.unknown_shift[date(2020, 1, 1)], 1)
        self.assertTrue(report.unknown_shift_months)
        self.assertFalse(report.is_valid)
        self.assertTrue(report.reconciliation_failures)


class FrontierTests(TestCase):
    def test_frontier_stops_at_first_gap(self):
        present = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 5, 1)]
        self.assertEqual(contiguous_frontier(present, date(2020, 1, 1)), date(2020, 3, 1))

    def test_frontier_none_when_start_missing(self):
        self.assertIsNone(contiguous_frontier([date(2020, 2, 1)], date(2020, 1, 1)))


class SeriesTests(TestCase):
    def setUp(self):
        from tests.helpers import make_caller

        self.shifts = make_canonical_shifts()
        add_calls.caller_id = make_caller().caller_id

    def test_build_series_excludes_missing_but_keeps_real_zero(self):
        add_calls(self.shifts[1], date(2020, 1, 5), 3)
        add_calls(self.shifts[3], date(2020, 1, 5), 1)
        add_calls(self.shifts[1], date(2020, 2, 5), 2)

        agg = aggregate_monthly(date(2020, 1, 1), date(2020, 3, 1))
        night = build_series(agg, "night")

        # Jan is observed with a genuine zero night; Mar is missing entirely.
        self.assertEqual(list(night.frame["y"]), [0, 0])
        self.assertEqual([d.date() for d in night.frame["ds"]], [date(2020, 1, 1), date(2020, 2, 1)])
        self.assertEqual(night.missing_months, [date(2020, 3, 1)])

    def test_resolve_window_uses_contiguous_frontier(self):
        for month in (1, 2, 3):
            add_calls(self.shifts[1], date(2020, month, 5), 2)
        add_calls(self.shifts[1], date(2020, 6, 5), 2)  # gap at April/May

        start, end = resolve_window(start="2020-01")

        self.assertEqual(start, date(2020, 1, 1))
        self.assertEqual(end, date(2020, 3, 1))

    def test_resolve_window_excludes_in_progress_month(self):
        today = date.today()
        current = date(today.year, today.month, 1)
        previous = add_months(current, -1)
        add_calls(self.shifts[1], previous.replace(day=5), 2)
        add_calls(self.shifts[1], current.replace(day=1), 2)

        start, end = resolve_window(start=previous)

        # The in-progress month is never used as training data.
        self.assertEqual(end, previous)

    def test_resolve_window_respects_explicit_incomplete_end(self):
        today = date.today()
        current = date(today.year, today.month, 1)
        previous = add_months(current, -1)
        add_calls(self.shifts[1], previous.replace(day=5), 2)
        add_calls(self.shifts[1], current.replace(day=1), 2)

        # An explicitly supplied endpoint is honoured (caller opted in).
        _, end = resolve_window(start=previous, end=current)
        self.assertEqual(end, current)


class ProphetForecastTests(TestCase):
    def setUp(self):
        from tests.helpers import make_caller

        self.shifts = make_canonical_shifts()
        add_calls.caller_id = make_caller().caller_id

    def _monthly_rows(self, months, per_month):
        for index, month in enumerate(months):
            counts = per_month(index)
            add_calls(self.shifts[1], month, counts[0])
            add_calls(self.shifts[3], month, counts[1])
            add_calls(self.shifts[4], month, counts[2])

    def test_fit_and_forecast_returns_monthly_bounds(self):
        self._monthly_rows(
            [date(2020, m, 1) for m in range(1, 13)],
            lambda i: (10 + i, 8 + i, 4 + i),
        )
        agg = aggregate_monthly(date(2020, 1, 1), date(2020, 12, 1))
        series = build_series(agg, "total")

        config = ProphetConfig(yearly_seasonality=False, uncertainty_samples=200)
        result = fit_and_forecast(series.frame, horizon=3, series="total", config=config)

        self.assertEqual(result.horizon, 3)
        self.assertEqual(len(result.frame), 3)
        self.assertEqual(result.last_observed, date(2020, 12, 1))
        self.assertEqual(
            [d.date() for d in result.frame["ds"]],
            [date(2021, 1, 1), date(2021, 2, 1), date(2021, 3, 1)],
        )
        self.assertTrue((result.frame["yhat_lower"] <= result.frame["yhat_upper"]).all())
        self.assertIn("yhat", result.frame.columns)
        self.assertEqual(result.prophet_version, prophet_version())

    def test_clamped_removes_negative_values(self):
        import pandas as pd

        from apps.forecast.services.prophet_model import SeriesForecast

        fc = SeriesForecast(
            series="total",
            last_observed=date(2020, 12, 1),
            horizon=1,
            frame=pd.DataFrame(
                {"ds": pd.to_datetime(["2021-01-01"]), "yhat": [-3.0], "yhat_lower": [-5.0], "yhat_upper": [1.0]}
            ),
        )
        clamped = fc.clamped()
        self.assertEqual(float(clamped["yhat"].iloc[0]), 0.0)
        self.assertEqual(float(clamped["yhat_lower"].iloc[0]), 0.0)
        # Raw frame unchanged.
        self.assertEqual(float(fc.frame["yhat"].iloc[0]), -3.0)

    def test_rejects_empty_and_short_series(self):
        import pandas as pd

        empty = pd.DataFrame({"ds": pd.to_datetime([]), "y": []})
        with self.assertRaises(ValueError):
            fit_and_forecast(empty, horizon=3)
        with self.assertRaises(ValueError):
            fit_and_forecast(empty, horizon=0)


class PipelineTests(TestCase):
    def setUp(self):
        from tests.helpers import make_caller

        self.shifts = make_canonical_shifts()
        add_calls.caller_id = make_caller().caller_id

    def test_pipeline_produces_all_four_series(self):
        months = [add_months(date(2020, 1, 1), i) for i in range(18)]
        for i, month in enumerate(months):
            add_calls(self.shifts[1], month, 10 + i % 5)
            add_calls(self.shifts[3], month, 8 + i % 4)
            add_calls(self.shifts[4], month, 3 + i % 3)

        config = ProphetConfig(yearly_seasonality=False, uncertainty_samples=100)
        result = run_forecast_pipeline(
            start="2020-01",
            end="2021-06",
            horizon=3,
            config=config,
        )

        self.assertEqual(result.start, date(2020, 1, 1))
        self.assertEqual(result.end, date(2021, 6, 1))
        self.assertTrue(result.validation.is_valid)
        self.assertEqual(set(result.forecasts), {"total", "morning", "afternoon", "night"})
        for forecast in result.forecasts.values():
            self.assertEqual(len(forecast.frame), 3)

        payload = result.to_payload()
        self.assertEqual(payload["last_observed_month"], "2021-06-01")
        self.assertIn("2021-07-01", [row["month"] for row in payload["forecasts"]["total"]])

    def test_pipeline_refuses_unknown_shift_data(self):
        stray = ShiftCatalog.objects.create(
            shift_id=2, shift_start_time=time(0, 0), shift_end_time=time(8, 0)
        )
        add_calls(self.shifts[1], date(2020, 1, 5), 3)
        add_calls(stray, date(2020, 1, 6), 1)

        from apps.forecast.services import ForecastDataError

        with self.assertRaises(ForecastDataError) as ctx:
            run_forecast_pipeline(start="2020-01", end="2020-12", horizon=1)
        self.assertTrue(ctx.exception.validation.unknown_shift_months)
        self.assertFalse(ctx.exception.validation.is_valid)

