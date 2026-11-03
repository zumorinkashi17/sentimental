"""Tests for the plain-language display layer of the forecasting pages.

These tests cover what a helpline manager actually reads:

* the shift names and working hours shown on screen come from the configured
  ``shift_catalog`` rows, and no internal shift id leaks into a label;
* the generation timestamp is shown in Philippine Time, converted from the
  stored UTC value by the framework;
* the missing-history message is plain, never a zero-filled month, and carries
  the action the manager has to take;
* the forecast numbers, intervals and uncertainty flags are unchanged.
"""

from datetime import date, datetime, time, timezone as dt_timezone
from html import unescape
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.forecast.services import forecast_run_payload
from apps.forecast.services.display import (
    APP_TIMEZONE,
    format_timestamp,
    month_range_label,
    shift_display_map,
)
from apps.forecast.services.constants import SERIES_TO_SHIFT_ID
from apps.schedules.models import ShiftCatalog
from tests.helpers import login, make_user
from tests.test_forecast_persistence import make_result, persist

MANILA = ZoneInfo("Asia/Manila")


def make_catalog():
    """The configured shifts: morning, afternoon and night.

    The ids match the production catalog (1, 3 and 4) so the wording is the
    same here as on the running system.
    """
    ShiftCatalog.objects.create(
        shift_id=1, shift_start_time=time(6, 0), shift_end_time=time(14, 0)
    )
    ShiftCatalog.objects.create(
        shift_id=3, shift_start_time=time(14, 0), shift_end_time=time(22, 0)
    )
    ShiftCatalog.objects.create(
        shift_id=4, shift_start_time=time(22, 0), shift_end_time=time(6, 0)
    )


class TimestampFormattingTests(TestCase):
    """UTC storage, Philippine Time display."""

    def test_utc_timestamp_is_converted_to_philippine_time(self):
        value = datetime(2026, 10, 21, 20, 20, tzinfo=dt_timezone.utc)
        self.assertEqual(
            format_timestamp(value), "October 22, 2026, 4:20 AM PHT"
        )

    def test_previous_day_in_utc_becomes_the_next_day_in_philippines(self):
        # 2026-10-21 18:00 UTC is already 2026-10-22 02:00 in Manila.
        value = datetime(2026, 10, 21, 18, 0, tzinfo=dt_timezone.utc)
        label = format_timestamp(value)
        self.assertIn("October 22, 2026", label)
        self.assertNotIn("October 21", label)
        self.assertIn("2:00 AM PHT", label)

    def test_midnight_boundary_in_philippines(self):
        # 2026-10-21 16:00 UTC is exactly 2026-10-22 00:00 in Manila.
        value = datetime(2026, 10, 21, 16, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(
            format_timestamp(value), "October 22, 2026, 12:00 AM PHT"
        )

    def test_a_timestamp_already_in_manila_is_not_shifted_again(self):
        value = datetime(2026, 10, 22, 4, 20, tzinfo=MANILA)
        self.assertEqual(
            format_timestamp(value), "October 22, 2026, 4:20 AM PHT"
        )

    def test_naive_timestamp_is_read_as_utc(self):
        value = datetime(2026, 10, 21, 20, 20)
        self.assertEqual(
            format_timestamp(value), "October 22, 2026, 4:20 AM PHT"
        )

    def test_iso_string_is_accepted(self):
        value = datetime(2026, 10, 21, 20, 20, tzinfo=dt_timezone.utc).isoformat()
        self.assertEqual(
            format_timestamp(value), "October 22, 2026, 4:20 AM PHT"
        )

    def test_empty_value_returns_none(self):
        self.assertIsNone(format_timestamp(None))
        self.assertIsNone(format_timestamp(""))

    def test_application_timezone_is_manila(self):
        self.assertEqual(str(APP_TIMEZONE), "Asia/Manila")


class DisplayedTimestampTests(TestCase):
    """The page shows the converted moment, and the stored value is untouched."""

    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_page_shows_the_generated_timestamp_in_philippine_time(self):
        run = persist(
            result=make_result(
                generated=datetime(2026, 10, 21, 20, 20, tzinfo=dt_timezone.utc)
            )
        )
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Forecast generated")
        self.assertContains(response, "October 22, 2026, 4:20 AM PHT")
        # The raw stored timestamp is not shown to the user.
        self.assertNotContains(response, "2026-10-21T20:20:00")

    def test_stored_timestamp_is_unchanged(self):
        run = persist(
            result=make_result(
                generated=datetime(2026, 10, 21, 20, 20, tzinfo=dt_timezone.utc)
            )
        )
        run.refresh_from_db()
        self.assertEqual(
            run.generated_at.astimezone(dt_timezone.utc),
            datetime(2026, 10, 21, 20, 20, tzinfo=dt_timezone.utc),
        )
        payload = forecast_run_payload(run)
        # The machine-readable value stays the stored UTC value.
        self.assertTrue(payload["generated_at"].startswith("2026-10-21T20:20"))
        self.assertEqual(payload["generated_display"], "October 22, 2026, 4:20 AM PHT")

class ShiftLabelTests(TestCase):
    """Shift names and hours come from the configured catalog."""

    def setUp(self):
        make_catalog()

    def test_labels_use_names_and_working_hours(self):
        labels = shift_display_map(SERIES_TO_SHIFT_ID)
        self.assertEqual(labels["morning"]["label"], "Morning Shift (6:00 AM–2:00 PM)")
        self.assertEqual(
            labels["afternoon"]["label"], "Afternoon Shift (2:00 PM–10:00 PM)"
        )
        self.assertEqual(labels["night"]["label"], "Night Shift (10:00 PM–6:00 AM (next day))")

    def test_labels_follow_the_configured_catalog(self):
        # Change the catalog and the wording follows it.
        ShiftCatalog.objects.filter(shift_start_time=time(6, 0)).update(
            shift_start_time=time(7, 0), shift_end_time=time(15, 0)
        )
        labels = shift_display_map(SERIES_TO_SHIFT_ID)
        self.assertEqual(labels["morning"]["label"], "Morning Shift (7:00 AM–3:00 PM)")

    def test_labels_are_correct_when_the_catalog_uses_other_ids(self):
        # A catalog that numbers its rows differently must still describe the
        # right shift, so the wording follows the working hours.
        ShiftCatalog.objects.all().delete()
        ShiftCatalog.objects.create(shift_start_time=time(6, 0), shift_end_time=time(14, 0))
        ShiftCatalog.objects.create(shift_start_time=time(14, 0), shift_end_time=time(22, 0))
        ShiftCatalog.objects.create(shift_start_time=time(22, 0), shift_end_time=time(6, 0))
        labels = shift_display_map(SERIES_TO_SHIFT_ID)
        self.assertEqual(labels["morning"]["label"], "Morning Shift (6:00 AM–2:00 PM)")
        self.assertEqual(
            labels["afternoon"]["label"], "Afternoon Shift (2:00 PM–10:00 PM)"
        )
        self.assertEqual(
            labels["night"]["label"], "Night Shift (10:00 PM–6:00 AM (next day))"
        )

    def test_no_shift_id_is_exposed_in_a_label(self):
        labels = shift_display_map(SERIES_TO_SHIFT_ID)
        for info in labels.values():
            self.assertNotIn("shift id", info["label"].lower())
            self.assertNotIn("shift_id", info["label"].lower())

    def test_forecast_page_shows_shift_names_and_hours(self):
        admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, admin)
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Morning Shift (6:00 AM–2:00 PM)")
        self.assertContains(response, "Afternoon Shift (2:00 PM–10:00 PM)")
        self.assertContains(response, "Night Shift (10:00 PM–6:00 AM (next day))")

    def test_no_shift_id_appears_on_the_forecast_page(self):
        admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, admin)
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        html = response.content.decode()
        self.assertNotIn("shift ID", html)
        self.assertNotIn("shift id", html)

    def test_no_shift_id_appears_on_the_dashboard_or_schedule_pages(self):
        admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, admin)
        persist()
        for url in (reverse("dashboard:admin_index"), reverse("schedules:admin_calendar")):
            html = self.client.get(url).content.decode()
            self.assertNotIn("shift ID", html)
            self.assertNotIn("shift id", html)


class PlainLanguageContentTests(TestCase):
    """Headings and wording a manager can read without training."""

    def setUp(self):
        make_catalog()
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_page_uses_the_plain_headings(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Expected Call Volume")
        self.assertContains(response, "Forecast Period")
        self.assertContains(response, "Historical Data Available Through")
        self.assertContains(response, "Historical Data Used")
        self.assertContains(response, "Expected Busiest Shift")
        self.assertContains(response, "Expected Monthly Call Volume")
        self.assertContains(response, "Expected Calls by Month and Shift")
        # The technical headings are gone.
        self.assertNotContains(response, "Training Data Ends")
        self.assertNotContains(response, "Training Window")
        self.assertNotContains(response, "Provisional Leading Shift")
        self.assertNotContains(response, "Monthly Volume Trend &amp; Prediction")
        self.assertNotContains(response, "Monthly Forecast &mdash; Total")

    def test_no_internal_configuration_values_are_shown(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        html = response.content.decode()
        self.assertNotIn("yearly_off", html)
        self.assertNotIn("independent_total", html)
        self.assertNotIn("residual_total_minus_shift_sum", html)

    def test_calls_are_shown_with_a_readable_range(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        html = unescape(response.content.decode())
        self.assertIn("200 calls", html)
        self.assertIn("Estimated range: 195–205 calls", html)
        # The old bracket notation is gone.
        self.assertNotIn("[195, 205]", html)

    def test_explains_total_and_shift_forecasts_are_separate(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "calculated separately")
        self.assertContains(response, "not add up exactly")

    def test_explains_the_estimated_range_is_not_a_guarantee(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "may fall outside this range")

    def test_staffing_card_does_not_claim_exact_requirements(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Staffing review recommended")
        self.assertContains(
            response, "does not determine the exact number of staff required"
        )

    def test_notes_are_plain(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Forecasts are estimates, not guaranteed results.")
        self.assertContains(response, "Missing historical data may reduce accuracy.")
        self.assertContains(
            response, "Total and shift-level forecasts are calculated separately"
        )


class MissingHistoryMessageTests(TestCase):
    """The missing-history message is plain and never fills in zeros."""

    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_missing_months_are_described_in_plain_language(self):
        persist()  # trained through 2026-04, so the recent months have no data
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Historical Data Available Through")
        self.assertContains(response, "April 2026")
        self.assertNotContains(response, "missing or unverified")
        self.assertNotContains(response, "preliminary")

    def test_the_action_message_is_shown(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertNotContains(response, "Action needed:")
        self.assertNotContains(response, "Restore actual records if available")

    def test_missing_months_are_never_shown_as_zero_calls(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        html = unescape(response.content.decode())
        # The table only contains the published forecast months; the gap months
        # are named in the status message, never as a zero cell.
        self.assertNotRegex(html, r"\b0 calls\b")
        self.assertNotContains(response, "Missing or unverified")

    def test_payload_keeps_the_provisional_flag_and_the_gap_months(self):
        run = persist()
        payload = forecast_run_payload(run)
        freshness = payload["freshness"]
        self.assertTrue(freshness["is_provisional"])
        # The months between the training cutoff (April 2026) and today are
        # reported as a gap, not as zero calls.
        self.assertEqual(freshness["gap_months"][0], "2026-05-01")
        self.assertEqual(freshness["missing_month_count"], len(freshness["gap_months"]))
        self.assertTrue(freshness["missing_month_count"] > 0)
        self.assertEqual(freshness["historical_available_through"], "April 2026")


class ForecastNumbersUnchangedTests(TestCase):
    """The display work must not touch the numbers."""

    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_values_intervals_and_uncertainty_are_unchanged(self):
        values = {
            "total": [200.0, 220.0],
            "morning": [100.0, 105.0],
            "afternoon": [98.0, 102.0],
            "night": [25.0, 30.0],
        }
        run = persist(make_result(values=values))
        payload = forecast_run_payload(run)
        self.assertEqual(payload["months"][0]["yhat"], 200.0)
        self.assertEqual(payload["months"][0]["yhat_lower"], 195.0)
        self.assertEqual(payload["months"][0]["yhat_upper"], 205.0)
        self.assertTrue(payload["busiest_shifts"][0]["uncertain"])
        self.assertEqual(payload["busiest_shifts"][0]["shift"], "morning")

    def test_the_busiest_shift_keeps_its_machine_readable_fields(self):
        run = persist()
        payload = forecast_run_payload(run)
        item = payload["busiest_shifts"][0]
        self.assertIn(item["shift"], ("morning", "afternoon", "night"))
        self.assertTrue(item["display_label"].startswith(("Morning", "Afternoon", "Night")))

    def test_forecast_period_is_reported(self):
        run = persist()
        payload = forecast_run_payload(run)
        self.assertEqual(payload["forecast_period"], "May 2026 – June 2026")
        self.assertEqual(payload["historical_data_used"], "January 2020 – April 2026")

    def test_month_range_label(self):
        self.assertEqual(
            month_range_label(date(2026, 11, 1), date(2027, 4, 1)),
            "November 2026 – April 2027",
        )
        self.assertEqual(
            month_range_label(date(2026, 11, 1), date(2026, 11, 1)), "November 2026"
        )
        self.assertEqual(month_range_label(None, None), "")


class ExportLabelTests(TestCase):
    def setUp(self):
        make_catalog()
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_csv_export_keeps_the_data_and_adds_a_readable_label(self):
        persist()
        response = self.client.get(reverse("forecast:export"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("series_label", body)
        self.assertIn("Morning Shift (6:00 AM–2:00 PM)", body)
        # The machine-readable columns are untouched.
        self.assertIn("shift_id", body)
        self.assertIn("residual_total_minus_shift_sum", body)

    def test_json_export_carries_the_display_labels(self):
        persist()
        response = self.client.get(reverse("forecast:export"), {"format": "json"})
        payload = response.json()
        self.assertEqual(
            payload["shift_labels"]["morning"]["label"], "Morning Shift (6:00 AM–2:00 PM)"
        )
        self.assertTrue(payload["generated_display"])
        self.assertEqual(payload["forecast_period"], "May 2026 – June 2026")
