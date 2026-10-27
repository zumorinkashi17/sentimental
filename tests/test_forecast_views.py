"""Tests for the Phase 5 Call Volume Forecast page and its export endpoint."""

import csv
import json
from datetime import date
from html import unescape
from io import StringIO

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.forecast.services import storage
from tests.helpers import login, make_user
from tests.test_forecast_persistence import persist, make_result


def _admin():
    return make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)


class ForecastPageAccessTests(TestCase):
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("forecast:prediction"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_responder_is_redirected_away(self):
        user = make_user(role=User.RoleChoices.RESPONDER)
        login(self.client, user)
        response = self.client.get(reverse("forecast:prediction"))
        self.assertEqual(response.status_code, 302)

    def test_admin_can_view_page(self):
        admin = _admin()
        login(self.client, admin)
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertEqual(response.status_code, 200)


class ForecastPageContentTests(TestCase):
    def setUp(self):
        self.admin = _admin()
        login(self.client, self.admin)

    def test_no_current_run_does_not_crash(self):
        response = self.client.get(reverse("forecast:prediction"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["forecast_available"])
        self.assertContains(response, "No forecast available")

    def test_displays_run_metadata(self):
        run = persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertTrue(response.context["forecast_available"])
        html = unescape(response.content.decode())
        # The run metadata is shown in plain language.
        self.assertIn("Historical Data Used", html)
        self.assertIn("January 2020 – April 2026", html)
        self.assertIn("Historical Data Available Through", html)
        self.assertIn("Forecast Period", html)
        # The machine-readable values stay available in the context.
        self.assertEqual(response.context["model_config_name"], "yearly_off")
        self.assertEqual(response.context["training_start"], "2020-01-01")
        self.assertEqual(response.context["horizon_months"], 2)

    def test_displays_monthly_total_and_every_shift(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        context = response.context
        labels = [row["label"] for row in context["display_rows"]]
        self.assertEqual(
            labels,
            [
                "Total calls (all shifts)",
                "Morning Shift (6:00 AM–2:00 PM)",
                "Afternoon Shift (2:00 PM–10:00 PM)",
                "Night Shift (10:00 PM–6:00 AM (next day))",
            ],
        )
        # Total row carries the persisted value for both months.
        totals = [cell["yhat"] for cell in context["display_rows"][0]["cells"]]
        self.assertEqual(totals, [200.0, 220.0])
        # Month headers rendered.
        self.assertContains(response, "May 2026")
        self.assertContains(response, "Jun 2026")

    def test_displays_prediction_intervals(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        first_total = response.context["display_rows"][0]["cells"][0]
        self.assertEqual(first_total["yhat_lower"], 195.0)
        self.assertEqual(first_total["yhat_upper"], 205.0)

    def test_shows_uncertainty_warning(self):
        values = {
            "total": [200.0, 220.0],
            "morning": [100.0, 105.0],
            "afternoon": [98.0, 102.0],
            "night": [25.0, 30.0],
        }
        persist(make_result(values=values))
        response = self.client.get(reverse("forecast:prediction"))
        self.assertTrue(response.context["any_busiest_uncertain"])
        self.assertEqual(response.context["uncertain_months"], 2)
        self.assertContains(response, "uncertain")
        self.assertContains(response, "Busiest Shift Confidence")
        self.assertContains(response, "2 of 2 months are uncertain")

    def test_reconciliation_is_explained_without_unallocated_wording(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        # The total and the shifts are explained as separate calculations.
        self.assertContains(response, "calculated separately")
        # The residual is never presented as a labelled figure named
        # "Unallocated Calls" (the disclaimer only name-drops it to reject it).
        self.assertNotContains(response, "Unallocated Calls")
        # It stays available for auditing in the export.
        export = self.client.get(reverse("forecast:export"))
        self.assertIn("residual_total_minus_shift_sum", export.content.decode())


class ForecastExportTests(TestCase):
    def setUp(self):
        self.admin = _admin()
        login(self.client, self.admin)

    def test_export_requires_admin(self):
        anon = self.client_class()
        response = anon.get(reverse("forecast:export"))
        self.assertEqual(response.status_code, 302)

    def test_export_404_when_no_run(self):
        response = self.client.get(reverse("forecast:export"))
        self.assertEqual(response.status_code, 404)

    def test_csv_export_matches_persisted_values(self):
        run = persist()
        response = self.client.get(reverse("forecast:export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])

        rows = list(csv.DictReader(StringIO(response.content.decode("utf-8"))))
        # 2 months x 4 series.
        self.assertEqual(len(rows), 8)
        self.assertEqual({r["series"] for r in rows}, {"total", "morning", "afternoon", "night"})
        self.assertEqual({r["month"] for r in rows}, {"2026-05-01", "2026-06-01"})
        self.assertEqual({r["shift_id"] for r in rows}, {"", "1", "3", "4"})

        total_may = next(r for r in rows if r["series"] == "total" and r["month"] == "2026-05-01")
        self.assertEqual(float(total_may["yhat"]), 200.0)
        self.assertEqual(float(total_may["yhat_lower"]), 195.0)
        self.assertEqual(float(total_may["yhat_upper"]), 205.0)
        # Residual stored on total rows only, matching the persisted model row.
        persisted = storage.run_month_map(run)["total"][date(2026, 5, 1)]
        self.assertAlmostEqual(
            float(total_may["residual_total_minus_shift_sum"]),
            round(persisted["residual_total_minus_shift_sum"], 2),
        )
        for name in ("morning", "afternoon", "night"):
            row = next(r for r in rows if r["series"] == name and r["month"] == "2026-05-01")
            self.assertEqual(row["residual_total_minus_shift_sum"], "")

    def test_json_export_matches_persisted_run(self):
        run = persist()
        response = self.client.get(reverse("forecast:export"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["run_id"], run.run_id)
        self.assertEqual(payload["model_config_name"], "yearly_off")
        self.assertEqual(len(payload["months"]), 2)
        self.assertEqual(payload["months"][0]["yhat"], 200.0)

    def test_export_reflects_new_current_run_not_old(self):
        persist()
        persist(
            make_result(values={
                "total": [999.0, 1000.0],
                "morning": [500.0, 510.0],
                "afternoon": [300.0, 310.0],
                "night": [100.0, 110.0],
            })
        )
        response = self.client.get(reverse("forecast:export"))
        rows = list(csv.DictReader(StringIO(response.content.decode("utf-8"))))
        total_may = next(r for r in rows if r["series"] == "total" and r["month"] == "2026-05-01")
        self.assertEqual(float(total_may["yhat"]), 999.0)
