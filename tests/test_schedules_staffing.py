"""Phase 7 tests: the Shift Schedules page reads the shared persisted run."""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.forecast.services import current_forecast_run, forecast_run_payload
from apps.schedules.models import ShiftSchedule
from apps.schedules.services import staffing_review_context
from tests.helpers import login, make_shift_schedule, make_user
from tests.test_forecast_persistence import make_result, persist


UNCERTAIN_VALUES = {
    "total": [200.0, 220.0],
    "morning": [100.0, 105.0],
    "afternoon": [98.0, 102.0],
    "night": [25.0, 30.0],
}
CLEAR_VALUES = {
    "total": [300.0, 320.0],
    "morning": [200.0, 210.0],
    "afternoon": [50.0, 52.0],
    "night": [20.0, 21.0],
}
SHIFT_LABELS = {
    "Morning Shift (6:00 AM–2:00 PM)",
    "Afternoon Shift (2:00 PM–10:00 PM)",
    "Night Shift (10:00 PM–6:00 AM (next day))",
}


class StaffingReviewContextTests(TestCase):
    def test_unavailable_without_run(self):
        context = staffing_review_context()
        self.assertFalse(context["available"])
        self.assertEqual(context["months"], [])
        self.assertEqual(context["review_count"], 0)
        self.assertIn("No forecast run", context["reason"])

    def test_ignores_non_current_run(self):
        persist(is_current=False)
        self.assertFalse(staffing_review_context()["available"])

    def test_matches_shared_run_payload(self):
        run = persist()
        payload = forecast_run_payload(run)
        context = staffing_review_context()

        self.assertTrue(context["available"])
        self.assertEqual(
            [m["month"] for m in context["months"]],
            [m["month"] for m in payload["months"]],
        )
        self.assertEqual(
            [m["total"] for m in context["months"]],
            [m["yhat"] for m in payload["months"]],
        )
        self.assertEqual(context["generated_at"], payload["generated_at"])
        self.assertEqual(context["model_config_name"], payload["model_config_name"])

    def test_monthly_values_use_recorded_shift_categories(self):
        persist()
        context = staffing_review_context()
        self.assertEqual(context["total_months"], 2)
        for month in context["months"]:
            self.assertIn(month["leading_shift"], SHIFT_LABELS)
            # 80% interval from the persisted total row.
            self.assertEqual(month["total_lower"], month["total"] - 5.0)

    def test_uncertainty_flagged_when_intervals_overlap(self):
        persist(make_result(values=UNCERTAIN_VALUES))
        context = staffing_review_context()
        self.assertTrue(context["any_uncertain"])
        self.assertEqual(context["review_count"], context["total_months"])
        for month in context["months"]:
            self.assertTrue(month["uncertain"])
            self.assertTrue(month["reason"])

    def test_confident_when_gap_is_clear(self):
        persist(make_result(values=CLEAR_VALUES))
        context = staffing_review_context()
        self.assertFalse(context["any_uncertain"])
        self.assertEqual(context["review_count"], 0)
        for month in context["months"]:
            self.assertFalse(month["uncertain"])


class SchedulesPageStaffingTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)
        self.url = reverse("schedules:admin_calendar")

    def test_page_shows_forecast_backed_review(self):
        persist()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staffing Review")
        self.assertContains(response, "planning aid")
        self.assertContains(response, "May 2026")
        self.assertContains(response, "200 calls")
        self.assertContains(response, "Expected busiest shift: Morning Shift")

    def test_page_shows_uncertainty_warning(self):
        persist(make_result(values=UNCERTAIN_VALUES))
        response = self.client.get(self.url)
        self.assertContains(response, "uncertain")
        self.assertContains(response, "uncertain busiest shift")
        self.assertContains(response, "review coverage for those months as a precaution")

    def test_page_does_not_show_old_fabricated_alert(self):
        persist()
        response = self.client.get(self.url)
        self.assertNotContains(response, "Shortage Detected")
        self.assertNotContains(response, "40% surge")

    def test_unavailable_state_without_run(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staffing Review unavailable")
        self.assertContains(response, "No forecast run")
        self.assertNotContains(response, "200 calls")
        self.assertNotContains(response, "Shortage Detected")

    def test_existing_schedules_are_preserved(self):
        responder = make_user(email="r@example.com", first="Rhea", last="Cruz")
        schedule = make_shift_schedule(responder, on=date(2026, 1, 5), status="Scheduled")

        before = ShiftSchedule.objects.count()
        persist()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        # No schedule record was created, changed, or deleted by the forecast.
        self.assertEqual(ShiftSchedule.objects.count(), before)
        schedule.refresh_from_db()
        self.assertEqual(schedule.schedule_status, "Scheduled")
        self.assertContains(response, "Rhea Cruz")

    def test_existing_kpis_still_render(self):
        persist()
        response = self.client.get(self.url)
        self.assertContains(response, "Active Today")
        self.assertContains(response, "Active (Month)")
        self.assertContains(response, "Pending Day Offs")
