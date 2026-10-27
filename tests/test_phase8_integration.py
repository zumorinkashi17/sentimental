"""Phase 8 end-to-end verification across the three forecast-consuming pages.

These tests assert that the Dashboard AI card, the Call Volume Forecast page and
the Shift Schedules & Staffing page all read the *same* current persisted run -
same run id, generation timestamp, training window, model config, horizon,
monthly totals and shift forecasts - and that switching the current run switches
all three together without mixing data from different runs.
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.forecast.services import (
    SELECTED_MODEL_CONFIG_NAME,
    SELECTED_YEARLY_SEASONALITY,
    current_forecast_run,
    forecast_run_payload,
    run_month_map,
)
from apps.schedules.models import ShiftSchedule
from tests.helpers import login, make_shift_schedule, make_user
from tests.test_forecast_persistence import make_result, persist


RUN_A = {
    "total": [200.0, 220.0],
    "morning": [100.0, 105.0],
    "afternoon": [70.0, 75.0],
    "night": [25.0, 30.0],
}
RUN_B = {
    "total": [900.0, 910.0],
    "morning": [500.0, 505.0],
    "afternoon": [300.0, 310.0],
    "night": [100.0, 110.0],
}


class ThreePageConsistencyTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def _get_all(self):
        dashboard = self.client.get(reverse("dashboard:admin_index"))
        forecast = self.client.get(reverse("forecast:prediction"))
        schedules = self.client.get(reverse("schedules:admin_calendar"))
        for response in (dashboard, forecast, schedules):
            self.assertEqual(response.status_code, 200)
        return {
            "dashboard": dashboard.context["ai"],
            "forecast": forecast.context["forecast"],
            "forecast_rows": forecast.context["display_rows"],
            "staffing": schedules.context["staffing"],
        }

    def test_all_three_use_same_current_run_identity(self):
        run = persist()
        views = self._get_all()

        # Same run id everywhere it is exposed.
        self.assertEqual(views["forecast"]["run_id"], run.run_id)
        self.assertEqual(views["staffing"]["run_id"], run.run_id)
        self.assertEqual(views["dashboard"]["run_id"], run.run_id)

        # Same generation timestamp and training window.
        self.assertEqual(views["forecast"]["generated_at"], views["staffing"]["generated_at"])
        self.assertEqual(views["forecast"]["training_start"], views["staffing"]["training_start"])
        self.assertEqual(views["forecast"]["training_end"], views["staffing"]["training_end"])

        # Same model config and horizon.
        self.assertEqual(views["forecast"]["model_config_name"], "yearly_off")
        self.assertEqual(views["staffing"]["model_config_name"], "yearly_off")
        self.assertEqual(views["forecast"]["horizon_months"], views["staffing"]["horizon_months"])
        self.assertEqual(views["staffing"]["horizon_months"], 2)

    def test_monthly_totals_and_shifts_match_persisted_run(self):
        run = persist()
        views = self._get_all()
        data = run_month_map(run)

        forecast_totals = [m["yhat"] for m in views["forecast"]["months"]]
        staffing_totals = [m["total"] for m in views["staffing"]["months"]]
        self.assertEqual(forecast_totals, [200.0, 220.0])
        self.assertEqual(staffing_totals, forecast_totals)

        # Shift forecasts are the persisted per-series values.
        by_key = {row["key"]: [c["yhat"] for c in row["cells"]] for row in views["forecast_rows"]}
        self.assertEqual(by_key["total"], RUN_A["total"])
        self.assertEqual(by_key["morning"], RUN_A["morning"])
        self.assertEqual(by_key["afternoon"], RUN_A["afternoon"])
        self.assertEqual(by_key["night"], RUN_A["night"])
        for name in ("morning", "afternoon", "night"):
            self.assertEqual(
                by_key[name],
                [data[name][date(2026, 5, 1)]["yhat"], data[name][date(2026, 6, 1)]["yhat"]],
            )

        # Dashboard card reflects the first persisted month + matching shift.
        first_lead = views["staffing"]["months"][0]["leading_shift"]
        self.assertEqual(views["dashboard"]["predicted"], round(forecast_totals[0]))
        self.assertEqual(views["dashboard"]["leading_shift"], first_lead)

    def test_shift_ids_are_one_three_and_four(self):
        persist()
        response = self.client.get(reverse("forecast:export"))
        shift_ids = {row["shift_id"] for row in self._csv_rows(response)}
        self.assertEqual(shift_ids, {"", "1", "3", "4"})
        self.assertNotIn("2", shift_ids)

    def test_switching_current_run_switches_all_three_without_mixing(self):
        persist(make_result(values=RUN_A))
        persist(make_result(values=RUN_B))
        views = self._get_all()
        new_run = current_forecast_run()

        self.assertEqual(views["forecast"]["run_id"], new_run.run_id)
        self.assertEqual(views["staffing"]["run_id"], new_run.run_id)
        self.assertEqual(views["dashboard"]["run_id"], new_run.run_id)

        # New totals everywhere; none of the old run's numbers survive.
        self.assertEqual([m["yhat"] for m in views["forecast"]["months"]], RUN_B["total"])
        self.assertEqual([m["total"] for m in views["staffing"]["months"]], RUN_B["total"])
        self.assertEqual(views["dashboard"]["predicted"], 900)
        for value in (200.0, 220.0):
            self.assertNotIn(value, [m["total"] for m in views["staffing"]["months"]])

    def test_export_matches_the_displayed_page(self):
        run = persist()
        page = self.client.get(reverse("forecast:prediction"))
        export = self.client.get(reverse("forecast:export"))
        rows = self._csv_rows(export)

        self.assertEqual(export["Content-Type"], "text/csv")
        self.assertEqual({r["run_id"] for r in rows}, {str(run.run_id)})
        total_may = next(r for r in rows if r["series"] == "total" and r["month"] == "2026-05-01")
        page_total_may = page.context["display_rows"][0]["cells"][0]["yhat"]
        self.assertEqual(float(total_may["yhat"]), page_total_may)

    def _csv_rows(self, response):
        import csv
        from io import StringIO

        return list(csv.DictReader(StringIO(response.content.decode("utf-8"))))


class NoCurrentRunFallbackTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_all_three_pages_fall_back_safely(self):
        # A run exists but is not current -> every page must report unavailable.
        persist(is_current=False)

        dashboard = self.client.get(reverse("dashboard:admin_index"))
        forecast = self.client.get(reverse("forecast:prediction"))
        schedules = self.client.get(reverse("schedules:admin_calendar"))

        self.assertFalse(dashboard.context["ai"]["available"])
        self.assertEqual(dashboard.context["ai"]["run_id"], None)
        self.assertFalse(forecast.context["forecast"]["available"])
        self.assertFalse(schedules.context["staffing"]["available"])

        self.assertContains(dashboard, "Forecast Unavailable")
        self.assertContains(forecast, "No forecast available")
        self.assertContains(schedules, "Staffing Review unavailable")


class HonestyAndSafetyTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_selected_config_is_unchanged(self):
        self.assertEqual(SELECTED_MODEL_CONFIG_NAME, "yearly_off")
        self.assertFalse(SELECTED_YEARLY_SEASONALITY)

    def test_residual_is_not_unallocated_and_not_redistributed(self):
        run = persist()
        response = self.client.get(reverse("forecast:prediction"))
        # The page explains that the total and the shifts are separate
        # calculations, and never calls the difference unallocated calls.
        self.assertContains(response, "calculated separately")
        self.assertNotContains(response, "Unallocated Calls")

        # The residual is stored only on total rows; shifts keep raw values.
        data = run_month_map(run)
        for name in ("morning", "afternoon", "night"):
            for cell in data[name].values():
                self.assertIsNone(cell["residual_total_minus_shift_sum"])

        # It is still available for auditing in the export.
        export = self.client.get(reverse("forecast:export"))
        self.assertIn("residual_total_minus_shift_sum", export.content.decode())

    def test_staffing_page_is_a_planning_aid_not_a_guarantee(self):
        persist()
        response = self.client.get(reverse("schedules:admin_calendar"))
        self.assertContains(response, "planning aid")
        self.assertContains(response, "not a guarantee")
        self.assertContains(response, "does not determine the exact number of staff required")

    def test_review_flag_is_uncertainty_driven_wording(self):
        # Overlapping intervals -> all months uncertain -> review is a
        # precaution, never a confirmed shortage.
        persist(make_result(values={
            "total": [200.0, 220.0],
            "morning": [100.0, 105.0],
            "afternoon": [98.0, 102.0],
            "night": [25.0, 30.0],
        }))
        response = self.client.get(reverse("schedules:admin_calendar"))
        self.assertContains(response, "uncertain busiest shift")
        self.assertContains(response, "review coverage for those months as a precaution")
        self.assertNotContains(response, "Shortage Detected")
        self.assertNotContains(response, "confirmed shortage")

    def test_schedules_are_not_modified_by_forecast_rendering(self):
        responder = make_user(email="r@example.com", first="Rhea", last="Cruz")
        make_shift_schedule(responder, status="Scheduled")
        before = list(ShiftSchedule.objects.values_list("schedule_id", "schedule_status"))
        persist()
        self.client.get(reverse("schedules:admin_calendar"))
        after = list(ShiftSchedule.objects.values_list("schedule_id", "schedule_status"))
        self.assertEqual(before, after)


class AccessControlTests(TestCase):
    def test_forecast_page_and_export_require_admin(self):
        responder = make_user(email="r@example.com", role=User.RoleChoices.RESPONDER)
        login(self.client, responder)
        self.assertEqual(self.client.get(reverse("forecast:prediction")).status_code, 302)
        self.assertEqual(self.client.get(reverse("forecast:export")).status_code, 302)

        anon = self.client_class()
        self.assertEqual(anon.get(reverse("forecast:prediction")).status_code, 302)
        self.assertEqual(anon.get(reverse("forecast:export")).status_code, 302)
