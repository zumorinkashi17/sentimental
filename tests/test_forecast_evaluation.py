"""Tests for the Phase 3 evaluation framework and busiest-shift logic."""

from datetime import date
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase

from apps.forecast.services import busiest_shift as busiest
from apps.forecast.services import evaluate
from apps.forecast.services.evaluate import (
    ErrorRow,
    EvaluationSplit,
    PROPHET_YEARLY_ON,
    SEASONAL_NAIVE,
    filter_rows,
    horizon_bucket,
    make_origins,
    make_split,
    mae,
    metrics_from_rows,
    reconcile_shifts,
    seasonal_naive_predictions,
    summarize,
    wape,
)
from apps.forecast.services.preprocess import SeriesData
from apps.forecast.services.prophet_model import SeriesForecast


def _frame(months, values, lower=None, upper=None):
    lower = lower if lower is not None else [v - 1 for v in values]
    upper = upper if upper is not None else [v + 1 for v in values]
    return pd.DataFrame(
        {
            "ds": pd.to_datetime([date(y, m, 1) for y, m in months]),
            "yhat": values,
            "yhat_lower": lower,
            "yhat_upper": upper,
        }
    )


def fake_fit(frame, horizon, series="total", config=None):
    """Deterministic stand-in for Prophet: yhat = last observed + h."""
    last_ds = pd.to_datetime(frame["ds"]).max()
    last_y = float(frame["y"].iloc[-1])
    rows = []
    for h in range(1, horizon + 1):
        ds = last_ds + pd.DateOffset(months=h)
        rows.append({"ds": ds, "yhat": last_y + h, "yhat_lower": last_y + h - 1, "yhat_upper": last_y + h + 1})
    out = pd.DataFrame(rows)
    return SeriesForecast(series=series, last_observed=last_ds.date(), horizon=horizon, frame=out)


def make_series(name, months, values):
    frame = pd.DataFrame(
        {"ds": pd.to_datetime([date(y, m, 1) for y, m in months]), "y": values}
    )
    return SeriesData(
        name=name, frame=frame, missing_months=[], zero_months=[],
        first=date(months[0][0], months[0][1], 1), last=date(months[-1][0], months[-1][1], 1),
    )


def months_range(start_year, start_month, count):
    out = []
    y, m = start_year, start_month
    for _ in range(count):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
class MetricTests(SimpleTestCase):
    def test_mae_and_wape(self):
        actuals = [10, 20, 30]
        preds = [12, 18, 33]
        self.assertAlmostEqual(mae(actuals, preds), (2 + 2 + 3) / 3)
        value, reason = wape(actuals, preds)
        self.assertIsNone(reason)
        self.assertAlmostEqual(value, 100 * 7 / 60)

    def test_wape_undefined_when_actuals_sum_to_zero(self):
        value, reason = wape([0, 0], [1, 2])
        self.assertIsNone(value)
        self.assertIn("zero", reason)

    def test_metrics_from_empty_rows(self):
        metrics = metrics_from_rows([])
        self.assertEqual(metrics.n, 0)
        self.assertIsNone(metrics.wape)
        self.assertEqual(metrics.undefined_reason, "no rows")

    def test_horizon_bucket(self):
        self.assertEqual(horizon_bucket(1), "1-3")
        self.assertEqual(horizon_bucket(3), "1-3")
        self.assertEqual(horizon_bucket(4), "4-6")
        self.assertEqual(horizon_bucket(7), "7-12")
        self.assertEqual(horizon_bucket(12), "7-12")


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
class BaselineTests(SimpleTestCase):
    def test_seasonal_naive_uses_twelve_months_earlier(self):
        months = months_range(2019, 1, 24)
        values = list(range(1, 25))
        frame = pd.DataFrame(
            {"ds": pd.to_datetime([date(y, m, 1) for y, m in months]), "y": values}
        )
        preds = seasonal_naive_predictions(frame, date(2020, 6, 1), horizon=3)
        # 2020-07 <- 2019-07 (value 7), 2020-08 <- 2019-08 (8), 2020-09 <- 2019-09 (9)
        self.assertEqual(preds[date(2020, 7, 1)], 7.0)
        self.assertEqual(preds[date(2020, 8, 1)], 8.0)
        self.assertEqual(preds[date(2020, 9, 1)], 9.0)

    def test_baseline_none_when_history_missing(self):
        frame = pd.DataFrame({"ds": pd.to_datetime([date(2020, 1, 1)]), "y": [5]})
        preds = seasonal_naive_predictions(frame, date(2020, 1, 1), horizon=1)
        self.assertIsNone(preds[date(2020, 2, 1)])


# --------------------------------------------------------------------------- #
# Walk-forward
# --------------------------------------------------------------------------- #
class WalkForwardTests(SimpleTestCase):
    def test_records_prophet_and_baseline_without_leakage(self):
        months = months_range(2019, 1, 24)
        values = [10] * 12 + [20] * 12
        series = {"total": make_series("total", months, values)}
        origin = date(2020, 6, 1)

        with mock.patch.object(evaluate, "fit_and_forecast", fake_fit):
            rows = evaluate.walk_forward(
                series,
                [origin],
                horizon=3,
                configs={PROPHET_YEARLY_ON: None},
                include_baseline=True,
            )

        prophet_rows = [r for r in rows if r.model == PROPHET_YEARLY_ON]
        baseline_rows = [r for r in rows if r.model == SEASONAL_NAIVE]
        self.assertEqual(len(prophet_rows), 3)
        self.assertEqual(len(baseline_rows), 3)

        # No leakage: every target is strictly after its origin.
        self.assertTrue(all(r.target > r.origin for r in rows))

        # Fake prophet: last observed (2020-06, y=20) + h.
        by_target = {r.target: r.predicted for r in prophet_rows}
        self.assertEqual(by_target[date(2020, 7, 1)], 21.0)
        self.assertEqual(by_target[date(2020, 9, 1)], 23.0)

        # Baseline: value twelve months earlier (all 10).
        self.assertEqual({r.predicted for r in baseline_rows}, {10.0})

    def test_filter_rows_by_region(self):
        rows = [
            ErrorRow("total", "m", date(2024, 1, 1), date(2024, 6, 1), 5, 1.0, 1.0),
            ErrorRow("total", "m", date(2024, 6, 1), date(2025, 1, 1), 7, 1.0, 1.0),
        ]
        filtered = filter_rows(rows, targets_from=date(2025, 1, 1))
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].target, date(2025, 1, 1))


# --------------------------------------------------------------------------- #
# Splits
# --------------------------------------------------------------------------- #
class SplitTests(SimpleTestCase):
    def test_make_split_is_chronological(self):
        observed = []
        y, m = 2020, 1
        for _ in range(20):
            observed.append(date(y, m, 1))
            m += 1
            if m > 12:
                y, m = y + 1, 1

        split = make_split(observed, test_months=4, validation_months=6)
        self.assertEqual(split.test_start, observed[-4])
        self.assertEqual(split.test_end, observed[-1])
        self.assertEqual(split.validation_start, observed[-10])
        self.assertEqual(split.validation_end, observed[-5])
        self.assertTrue(split.validation_end < split.test_start)

    def test_make_split_rejects_short_history(self):
        with self.assertRaises(ValueError):
            make_split([date(2020, m, 1) for m in range(1, 6)], test_months=4, validation_months=6)

    def test_make_origins_are_before_end(self):
        observed = []
        y, m = 2020, 1
        for _ in range(30):
            observed.append(date(y, m, 1))
            m += 1
            if m > 12:
                y, m = y + 1, 1
        origins = make_origins(observed, observed[-1], count=5, max_horizon=12)
        self.assertEqual(len(origins), 5)
        self.assertTrue(all(o < observed[-1] for o in origins))
        self.assertEqual(origins, observed[-6:-1])


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
class ReconciliationTests(SimpleTestCase):
    def test_proportional_scaling_sums_to_independent_total(self):
        total = {date(2026, 1, 1): 100.0}
        shifts = {
            "morning": {date(2026, 1, 1): 40.0},
            "afternoon": {date(2026, 1, 1): 30.0},
            "night": {date(2026, 1, 1): 20.0},
        }
        reconciled = reconcile_shifts(total, shifts, "proportional")
        self.assertAlmostEqual(sum(reconciled[n][date(2026, 1, 1)] for n in shifts), 100.0)
        # Raw inputs are not mutated.
        self.assertEqual(shifts["morning"][date(2026, 1, 1)], 40.0)

    def test_raw_method_preserves_values(self):
        total = {date(2026, 1, 1): 100.0}
        shifts = {"morning": {date(2026, 1, 1): 40.0}, "night": {date(2026, 1, 1): 20.0}}
        raw = reconcile_shifts(total, shifts, "raw")
        self.assertEqual(raw["morning"][date(2026, 1, 1)], 40.0)

    def test_compare_reconciliation_reports_both_and_residual(self):
        month = date(2026, 1, 1)
        actual = {month: 100.0}
        independent = {month: 98.0}
        shifts = {
            "morning": {month: 40.0},
            "afternoon": {month: 30.0},
            "night": {month: 24.0},  # sum = 94
        }
        report = evaluate.compare_reconciliation(actual, independent, shifts)
        self.assertEqual(report["n_months"], 1)
        self.assertAlmostEqual(report["independent_total"]["mae"], 2.0)
        self.assertAlmostEqual(report["sum_of_shifts"]["mae"], 6.0)
        # Discrepancy is recorded as a residual, never as "unallocated calls".
        self.assertEqual(report["residual_total_minus_shift_sum"]["2026-01-01"], 4.0)
        self.assertNotIn("unallocated", report)


# --------------------------------------------------------------------------- #
# Busiest shift
# --------------------------------------------------------------------------- #
class BusiestShiftTests(SimpleTestCase):
    def _forecast(self, name, values, lower, upper):
        frame = _frame([(2026, 1), (2026, 2)], values, lower, upper)
        return SeriesForecast(series=name, last_observed=date(2025, 12, 1), horizon=2, frame=frame)

    def test_clear_winner_is_not_uncertain(self):
        forecasts = {
            "morning": self._forecast("morning", [80, 80], [70, 70], [90, 90]),
            "afternoon": self._forecast("afternoon", [40, 40], [30, 30], [50, 50]),
            "night": self._forecast("night", [10, 10], [5, 5], [15, 15]),
        }
        results = busiest.identify_busiest_shift(forecasts)
        self.assertEqual(results[0].shift, "morning")
        self.assertFalse(results[0].uncertain)
        self.assertEqual(results[0].runner_up, "afternoon")

    def test_overlapping_intervals_flagged_uncertain(self):
        forecasts = {
            "morning": self._forecast("morning", [60, 60], [40, 40], [80, 80]),
            "afternoon": self._forecast("afternoon", [58, 58], [38, 38], [78, 78]),
            "night": self._forecast("night", [10, 10], [5, 5], [15, 15]),
        }
        results = busiest.identify_busiest_shift(forecasts)
        self.assertEqual(results[0].shift, "morning")
        self.assertTrue(results[0].uncertain)
        self.assertIn("overlap", results[0].reason)

    def test_close_margin_flagged_uncertain(self):
        forecasts = {
            "morning": self._forecast("morning", [100, 100], [90, 90], [110, 110]),
            "afternoon": self._forecast("afternoon", [95, 95], [85, 85], [105, 105]),
        }
        results = busiest.identify_busiest_shift(forecasts)
        self.assertTrue(results[0].uncertain)

    def test_requires_two_shifts(self):
        forecasts = {"morning": self._forecast("morning", [10, 10], [5, 5], [15, 15])}
        with self.assertRaises(ValueError):
            busiest.identify_busiest_shift(forecasts)

    def test_hit_rate(self):
        actual = {date(2026, 1, 1): {"morning": 10, "afternoon": 20, "night": 5}}
        predicted = {date(2026, 1, 1): {"morning": 15, "afternoon": 25, "night": 5}}
        result = busiest.busiest_shift_hit_rate(actual, predicted)
        self.assertEqual(result["n_months"], 1)
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["hit_rate"], 1.0)


# --------------------------------------------------------------------------- #
# Full orchestration (with a deterministic fake model)
# --------------------------------------------------------------------------- #
class RunEvaluationTests(SimpleTestCase):
    def _series(self):
        months = months_range(2020, 1, 36)
        base = list(range(10, 46))
        series = {
            "total": make_series("total", months, base),
            "morning": make_series("morning", months, [b // 2 for b in base]),
            "afternoon": make_series("afternoon", months, [b // 3 for b in base]),
            "night": make_series("night", months, [b // 6 for b in base]),
        }
        return series, months

    @mock.patch.object(evaluate, "fit_and_forecast", fake_fit)
    def test_report_structure(self):
        series, months = self._series()
        observed = [date(y, m, 1) for y, m in months]
        split = make_split(observed, test_months=4, validation_months=6)
        origins = make_origins(observed, observed[-1], count=12)

        report = evaluate.run_evaluation(series, split, origins, max_horizon=3)

        self.assertIn("validation", report)
        self.assertIn("test", report)
        self.assertIn("seasonality", report)
        self.assertIn("reconciliation", report)
        self.assertIn("busiest_shift", report)
        self.assertIn("validation", report["reconciliation"])
        self.assertIn("test", report["reconciliation"])
        self.assertIsNotNone(report["reconciliation"]["test"]["independent_total"])
        self.assertIsNotNone(report["reconciliation"]["test"]["sum_of_shifts"])
        self.assertIn("shift_level", report["reconciliation"]["test"])
        self.assertTrue(report["busiest_shift"]["predictions"])
        self.assertIn("yearly_helps_on_validation", report["seasonality"])
        self.assertEqual(report["selection"]["selected_on"], "validation")
        self.assertIn(report["selection"]["config"], ("yearly_on", "yearly_off"))
        self.assertTrue(report["future"]["total"])
        self.assertTrue(report["future"]["busiest_shift"])

    @mock.patch.object(evaluate, "fit_and_forecast", fake_fit)
    def test_summarize_groups_by_model_and_series(self):
        series, months = self._series()
        observed = [date(y, m, 1) for y, m in months]
        rows = evaluate.walk_forward(
            {"total": series["total"]},
            origins=observed[-4:],
            horizon=2,
            configs={PROPHET_YEARLY_ON: None},
            include_baseline=True,
        )
        summary = summarize(rows)
        self.assertIn(PROPHET_YEARLY_ON, summary["by_model"])
        self.assertIn(SEASONAL_NAIVE, summary["by_model"])
        self.assertTrue(summary["by_horizon"])
