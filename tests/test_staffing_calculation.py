"""Unit tests for the staffing calculation service.

AHT values and staffing assumptions are maintained in backend code
(apps/staffing/services.py STAFFING CONFIGURATION section). Tests verify
the calculation logic uses those code constants.
"""

from datetime import date

from django.test import TestCase

from apps.schedules.staffing_service import calculate_staffing, ceil_value
from tests.test_forecast_persistence import make_result, persist


class CeilValueTests(TestCase):
    def test_ceil_whole(self):
        self.assertEqual(ceil_value(2.0), 2)

    def test_ceil_fractional(self):
        self.assertEqual(ceil_value(2.1), 3)
        self.assertEqual(ceil_value(0.01), 1)

    def test_ceil_zero_and_negative(self):
        self.assertEqual(ceil_value(0.0), 0)
        self.assertEqual(ceil_value(-1.5), 0)


class StaffingCalculationTests(TestCase):
    def test_unavailable_without_run(self):
        result = calculate_staffing()
        self.assertFalse(result.available)
        self.assertIn("No forecast run", result.reason)

    def test_default_aht_applied_to_all_shifts(self):
        # Default AHT is 20 minutes; morning/afternoon/night all have explicit
        # overrides (25/25/30) that differ from the default, so none use global.
        run = persist()
        result = calculate_staffing(run)

        self.assertTrue(result.available)
        expected = {"morning": 25.0, "afternoon": 25.0, "night": 30.0}
        for month in result.months:
            for shift in month["shifts"]:
                self.assertEqual(shift["aht_minutes"], expected[shift["series"]])
                self.assertFalse(shift["aht_used_global"])  # explicit override, differs from default 20
                self.assertEqual(shift["aht_status"], "sample_default")
                self.assertTrue(shift["aht_is_sample"])

    def test_workload_calculation(self):
        # 120 calls * 25 min / 60 = 50 workload hours
        run = persist(
            make_result(
                months=[date(2026, 5, 1)],
                values={"morning": [120.0], "afternoon": [0.0], "night": [0.0], "total": [120.0]},
            )
        )
        result = calculate_staffing(run)

        month = result.months[0]
        morning = month["shifts"][0]
        self.assertEqual(morning["forecast_calls"], 120.0)
        self.assertEqual(morning["workload_hours"], 50.0)

    def test_effective_available_hours(self):
        # 8 hrs * 22 days * (1 - 0.15) * 0.85 = 127.16
        run = persist()
        result = calculate_staffing(run)

        for month in result.months:
            for shift in month["shifts"]:
                self.assertAlmostEqual(shift["effective_available_hours"], 127.16, places=2)

    def test_minimum_staffing_applied(self):
        # Very low call volume -> workload-based staff < min -> min applied
        run = persist(
            make_result(
                months=[date(2026, 5, 1)],
                values={"morning": [1.0], "afternoon": [1.0], "night": [1.0], "total": [3.0]},
            )
        )
        result = calculate_staffing(run)

        month = result.months[0]
        for shift in month["shifts"]:
            self.assertEqual(shift["recommended_staff"], shift["min_staff"])
            self.assertGreaterEqual(shift["recommended_staff"], shift["workload_based_staff"])

    def test_workload_based_exceeds_minimum(self):
        # High call volume -> workload-based staff > min -> workload applied
        # Default AHT=25: 200 calls * 25 min / 60 = 83.33 workload hours
        # eff avail = 127.16 -> 0.66 staff -> ceil(1) but min=2 -> 2
        run = persist(
            make_result(
                months=[date(2026, 5, 1)],
                values={"morning": [200.0], "afternoon": [0.0], "night": [0.0], "total": [200.0]},
            )
        )
        result = calculate_staffing(run)

        month = result.months[0]
        morning = month["shifts"][0]
        # Workload-based = 83.33 / 127.16 = 0.66, min=2, recommended=2
        self.assertAlmostEqual(morning["workload_based_staff"], 0.6553, places=4)
        self.assertEqual(morning["recommended_staff"], 2)

    def test_rounding_preserves_fractional_internally(self):
        run = persist(
            make_result(
                months=[date(2026, 5, 1)],
                values={"morning": [10.0], "afternoon": [0.0], "night": [0.0], "total": [10.0]},
            )
        )
        result = calculate_staffing(run)

        month = result.months[0]
        morning = month["shifts"][0]
        # 10 * 25 / 60 = 4.17 workload hours; / 127.16 = 0.0328 staff
        self.assertAlmostEqual(morning["workload_based_staff"], 0.0328, places=4)
        # recommended is ceiling of max(0.0328, 2) = 2
        self.assertEqual(morning["recommended_staff"], 2)

    def test_missing_forecast_month(self):
        # Provide data for only one month; the other should be absent (not zero)
        months = [date(2026, 5, 1)]
        values = {
            "total": [200.0],
            "morning": [100.0],
            "afternoon": [70.0],
            "night": [30.0],
        }
        run = persist(make_result(months=months, values=values))
        result = calculate_staffing(run)

        self.assertEqual(len(result.months), 1)
        self.assertEqual(result.months[0]["month"], "2026-05-01")

    def test_totals_aggregated(self):
        run = persist()
        result = calculate_staffing(run)

        self.assertIn("total_calls", result.totals)
        self.assertIn("total_workload_hours", result.totals)
        self.assertIn("total_recommended_staff", result.totals)
        self.assertEqual(result.totals["month_count"], len(result.months))

    def test_assumptions_used_recorded(self):
        run = persist()
        result = calculate_staffing(run)

        self.assertEqual(result.assumptions_used["working_days_per_month"], 22)
        self.assertEqual(float(result.assumptions_used["shrinkage_rate"]), 0.15)
        self.assertEqual(float(result.assumptions_used["occupancy_factor"]), 0.85)
        self.assertEqual(result.assumptions_used["min_staff_morning"], 2)
        self.assertEqual(result.assumptions_used["min_staff_afternoon"], 2)
        self.assertEqual(result.assumptions_used["min_staff_night"], 2)

    def test_shift_names_and_hours(self):
        run = persist()
        result = calculate_staffing(run)

        expected = {
            "morning": ("Morning Shift", 8.0),
            "afternoon": ("Afternoon Shift", 8.0),
            "night": ("Night Shift", 8.0),
        }
        for month in result.months:
            for shift in month["shifts"]:
                name, hours = expected[shift["series"]]
                self.assertEqual(shift["shift_name"], name)
                self.assertEqual(shift["shift_hours"], hours)

    def test_aht_used_summary_recorded(self):
        run = persist()
        result = calculate_staffing(run)

        for series in ["morning", "afternoon"]:
            self.assertEqual(result.aht_used[series]["minutes"], 25.0)
        self.assertEqual(result.aht_used["night"]["minutes"], 30.0)
        for series in ["morning", "afternoon", "night"]:
            self.assertEqual(result.aht_used[series]["status"], "sample_default")

    def test_config_version_recorded(self):
        run = persist()
        result = calculate_staffing(run)

        self.assertIsNotNone(result.config_version)
        self.assertTrue(result.config_version.startswith("cfg-"))
        self.assertIsNotNone(result.calculation_timestamp)
