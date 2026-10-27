"""Tests for the Forecast Horizon Selector and the Generate Forecast action.

The generation policy under test is *future-anchored*: the published window
always starts in the month after the current calendar month, so a run whose
window has already elapsed is never presented as a current future forecast.
The pipeline itself is unchanged - the tests reuse the real storage, validation
and publication code and only replace the Prophet fitting step.
"""

from datetime import date, time
from io import StringIO
from unittest import mock

import csv
import pandas as pd
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.callers.models import CallSession
from apps.forecast.models import ForecastRun, ForecastRunMonth
from apps.forecast.services import (
    current_forecast_run,
    forecast_run_payload,
    run_month_map,
)
from apps.forecast.services.data import add_months, month_span, month_start
from apps.forecast.services.generation import (
    GenerationBusy,
    GenerationError,
    GenerationPlan,
    generate_forecast,
    generation_lock,
    plan_generation,
    publish_generation,
    validate_horizon,
)
from apps.forecast.services.pipeline import ForecastDataError, ForecastRunResult
from apps.forecast.services.preprocess import ValidationReport
from apps.forecast.services.prophet_model import SeriesForecast
from apps.schedules.models import ShiftCatalog
from tests.helpers import login, make_caller, make_user
from tests.test_forecast_persistence import make_result, persist
from tests.test_forecast_pipeline import make_canonical_shifts

TODAY = month_start(date.today())
HISTORY_START = date(2020, 1, 1)
# Six months of history-less months between the training cutoff and today,
# mirroring the real data gap (2026-05..2026-10 when today is 2026-10).
HISTORY_END = add_months(TODAY, -6)


def add_history(until=HISTORY_END, per_shift=2):
    """Create continuous monthly history so the training window resolves."""
    shifts = make_canonical_shifts()
    caller = make_caller()
    for month in month_span(HISTORY_START, until):
        for shift_id in (1, 3, 4):
            for _ in range(per_shift):
                CallSession.objects.create(
                    caller=caller,
                    shift_id=shift_id,
                    session_call_date=month,
                    session_time_called=time(9, 0),
                    session_risk_assessment="Low",
                    session_summarization="s",
                )
    return shifts


def make_plan(horizon, training_end=HISTORY_END, unobserved=None):
    """A plan equivalent to what the policy produces for the test data."""
    unobserved = unobserved if unobserved is not None else month_span(
        add_months(training_end, 1), TODAY
    )
    forecast_start = add_months(TODAY, 1)
    return GenerationPlan(
        horizon=horizon,
        training_start=HISTORY_START,
        training_end=training_end,
        as_of=TODAY,
        forecast_start=forecast_start,
        forecast_end=add_months(forecast_start, horizon - 1),
        generation_horizon=len(unobserved) + horizon,
        unobserved_months=unobserved,
    )


def make_generated_result(plan):
    """A synthetic pipeline result covering exactly the published months."""
    months = plan.published_months
    base = 100.0 * len(months)
    values = {
        "total": [base + 10.0 * index for index in range(len(months))],
        "morning": [base / 2 + 5.0 * index for index in range(len(months))],
        "afternoon": [base / 3 + 3.0 * index for index in range(len(months))],
        "night": [base / 6 + 1.0 * index for index in range(len(months))],
    }
    forecasts = {}
    for name, series_values in values.items():
        frame = pd.DataFrame(
            {
                "ds": pd.to_datetime(months),
                "yhat": series_values,
                "yhat_lower": [value - 5.0 for value in series_values],
                "yhat_upper": [value + 5.0 for value in series_values],
            }
        )
        forecasts[name] = SeriesForecast(
            series=name,
            last_observed=plan.training_end,
            horizon=plan.horizon,
            frame=frame,
            config={"yearly_seasonality": False},
            prophet_version="1.5.0",
        )
    return ForecastRunResult(
        start=plan.training_start,
        end=plan.training_end,
        horizon=plan.horizon,
        aggregates=None,
        validation=ValidationReport(start=plan.training_start, end=plan.training_end),
        series={},
        forecasts=forecasts,
    )


def fake_generate(horizon, as_of=None, config=None):
    """Replacement for the Prophet step: same contract, no fitting."""
    plan = make_plan(int(horizon))
    return make_generated_result(plan), plan


class HorizonValidationTests(TestCase):
    def test_supported_horizons_are_accepted(self):
        for horizon in (3, 6, 12):
            self.assertEqual(validate_horizon(horizon), horizon)
            self.assertEqual(validate_horizon(str(horizon)), horizon)

    def test_unsupported_horizons_are_rejected(self):
        for horizon in (0, 1, 2, 4, 9, 18, 24, -6):
            with self.assertRaises(GenerationError):
                validate_horizon(horizon)

    def test_non_numeric_horizons_are_rejected(self):
        for horizon in (None, "", "abc", "six"):
            with self.assertRaises(GenerationError):
                validate_horizon(horizon)


class GenerationPlanTests(TestCase):
    def setUp(self):
        add_history()

    def test_plan_publishes_exactly_the_requested_months(self):
        for horizon in (3, 6, 12):
            plan = plan_generation(horizon)
            self.assertEqual(len(plan.published_months), horizon)
            self.assertEqual(plan.horizon, horizon)

    def test_published_window_starts_after_the_current_month(self):
        plan = plan_generation(6)
        self.assertEqual(plan.forecast_start, add_months(TODAY, 1))
        self.assertEqual(plan.forecast_end, add_months(TODAY, 6))
        self.assertTrue(all(month > TODAY for month in plan.published_months))

    def test_generation_horizon_covers_the_unobserved_months(self):
        plan = plan_generation(6)
        self.assertEqual(len(plan.unobserved_months), 6)
        self.assertEqual(plan.unobserved_months[0], add_months(HISTORY_END, 1))
        self.assertEqual(plan.unobserved_months[-1], TODAY)
        self.assertEqual(plan.generation_horizon, 6 + 6)
        self.assertTrue(plan.provisional)

    def test_plan_reuses_the_validated_training_window(self):
        plan = plan_generation(3)
        self.assertEqual(plan.training_start, HISTORY_START)
        self.assertEqual(plan.training_end, HISTORY_END)

    def test_metadata_records_the_generation(self):
        metadata = plan_generation(12).as_metadata()
        self.assertEqual(metadata["policy"], "future_anchored")
        self.assertEqual(metadata["requested_horizon"], 12)
        self.assertEqual(metadata["generation_horizon"], 18)
        self.assertEqual(len(metadata["published_months"]), 12)
        self.assertEqual(len(metadata["unobserved_months"]), 6)
        self.assertTrue(metadata["provisional"])

    def test_gap_of_one_month_when_history_reaches_last_month(self):
        # Training cutoff is the previous month, so only the in-progress month
        # is skipped.
        plan = plan_generation(3, as_of=TODAY)
        self.assertEqual(len(plan.unobserved_months), 6)
        self.assertEqual(plan.generation_horizon, 9)


class GenerateForecastTests(TestCase):
    """One real end-to-end run through the existing Prophet pipeline."""

    def setUp(self):
        add_history()

    def test_generated_run_holds_exactly_the_published_months(self):
        result, plan = generate_forecast(3)
        self.assertEqual(len(plan.published_months), 3)
        for name, forecast in result.forecasts.items():
            months = [row.ds.date() for row in forecast.frame.itertuples(index=False)]
            self.assertEqual(months, plan.published_months, name)
        self.assertEqual(result.horizon, 3)

    def test_published_run_is_current_and_keeps_prior_history(self):
        previous = persist()
        result, plan = generate_forecast(6)
        run = publish_generation(result, plan)

        self.assertTrue(run.is_current)
        self.assertEqual(run.horizon_months, 6)
        self.assertEqual(
            sorted(set(run.months.values_list("month", flat=True))),
            plan.published_months,
        )
        self.assertEqual(run.months.count(), 4 * 6)
        # The previous run is preserved, just no longer current.
        self.assertFalse(ForecastRun.objects.get(pk=previous.pk).is_current)
        self.assertTrue(ForecastRunMonth.objects.filter(run=previous).exists())


class GenerateEndpointTests(TestCase):
    """The JSON contract kept for AJAX/API clients."""

    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)
        self.url = reverse("forecast:generate")

    def post(self, horizon=6, **extra):
        payload = {"horizon": horizon, "action": "generate"}
        payload.update(extra)
        return self.client.post(self.url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_anonymous_request_is_rejected(self):
        self.client.logout()
        response = self.client.post(
            self.url, {"horizon": 6, "action": "generate"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_responder_cannot_generate(self):
        responder = make_user(email="resp@example.com", role=User.RoleChoices.RESPONDER)
        login(self.client, responder)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_inactive_admin_cannot_generate(self):
        inactive = make_user(
            email="old@example.com",
            role=User.RoleChoices.ADMIN,
            status=User.StatusChoices.INACTIVE,
        )
        login(self.client, inactive)
        response = self.post()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_get_is_not_allowed(self):
        response = self.client.get(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_request_without_the_explicit_action_marker_is_refused(self):
        # An implicit submission (for example Enter in the selector) does not
        # carry the button's name/value, so it must not generate anything.
        response = self.client.post(
            self.url, {"horizon": 6}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_unsupported_horizon_is_rejected(self):
        for horizon in (0, 4, 9, 24, "abc"):
            response = self.post(horizon)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json()["ok"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_missing_horizon_is_rejected(self):
        response = self.client.post(
            self.url, {"action": "generate"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_successful_generation_publishes_exactly_the_requested_months(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            for horizon in (3, 6, 12):
                response = self.post(horizon)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertTrue(data["ok"])
                self.assertEqual(data["horizon"], horizon)
                self.assertEqual(len(data["months"]), horizon)

                run = current_forecast_run()
                self.assertEqual(run.horizon_months, horizon)
                self.assertEqual(
                    sorted(set(run.months.values_list("month", flat=True))),
                    sorted(date.fromisoformat(month) for month in data["months"]),
                )
                self.assertEqual(run.months.count(), 4 * horizon)

    def test_generated_run_records_its_metadata(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            self.post(6)
        run = current_forecast_run()
        generation = run.evaluation_snapshot["generation"]
        self.assertEqual(generation["policy"], "future_anchored")
        self.assertEqual(generation["requested_horizon"], 6)
        self.assertEqual(generation["generation_horizon"], 12)
        self.assertEqual(len(generation["published_months"]), 6)
        self.assertEqual(len(generation["unobserved_months"]), 6)
        self.assertTrue(generation["provisional"])
        self.assertEqual(run.model_config_name, "yearly_off")
        self.assertFalse(run.yearly_seasonality)

    def test_previous_run_is_preserved_and_replaced_as_current(self):
        previous = persist()
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            self.post(6)
        self.assertEqual(ForecastRun.objects.count(), 2)
        self.assertFalse(ForecastRun.objects.get(pk=previous.pk).is_current)
        self.assertTrue(current_forecast_run().is_current)
        self.assertTrue(ForecastRunMonth.objects.filter(run=previous).exists())

    def test_evaluation_snapshot_is_carried_forward(self):
        persist(evaluation_snapshot={"selected_model": "prophet_yearly_off"})
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            self.post(3)
        run = current_forecast_run()
        self.assertEqual(run.evaluation_snapshot["selected_model"], "prophet_yearly_off")
        self.assertIn("generation", run.evaluation_snapshot)

    def test_failed_generation_publishes_nothing(self):
        previous = persist()
        validation = ValidationReport(start=HISTORY_START, end=HISTORY_END)
        validation.issues.append("synthetic failure")
        with mock.patch(
            "apps.forecast.views.generate_forecast",
            side_effect=ForecastDataError(validation),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(ForecastRun.objects.count(), 1)
        self.assertEqual(current_forecast_run().pk, previous.pk)
        self.assertTrue(current_forecast_run().is_current)

    def test_unexpected_failure_leaves_the_previous_run_current(self):
        previous = persist()
        with mock.patch(
            "apps.forecast.views.generate_forecast", side_effect=RuntimeError("boom")
        ):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(current_forecast_run().pk, previous.pk)

    def test_refused_publication_writes_nothing(self):
        previous = persist()
        with mock.patch(
            "apps.forecast.views.generate_forecast", side_effect=fake_generate
        ), mock.patch(
            "apps.forecast.views.publish_generation",
            side_effect=GenerationError("the generated months did not match"),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(ForecastRun.objects.count(), 1)
        self.assertEqual(current_forecast_run().pk, previous.pk)
        self.assertTrue(current_forecast_run().is_current)

    def test_concurrent_request_is_rejected(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            with generation_lock():
                response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_page_load_never_generates_a_run(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ForecastRun.objects.count(), 1)


class GenerateFormSubmissionTests(TestCase):
    """A plain browser form post is answered with a page, never with JSON."""

    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)
        self.url = reverse("forecast:generate")
        self.page_url = reverse("forecast:prediction")

    def post(self, horizon=3, **extra):
        payload = {"horizon": horizon, "action": "generate"}
        payload.update(extra)
        return self.client.post(self.url, payload)

    def test_successful_form_post_redirects_back_to_the_forecast_page(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            response = self.post(3)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response["Location"].startswith(self.page_url))
        self.assertIn("generated=", response["Location"])
        self.assertIn("horizon=3", response["Location"])
        # The body is a redirect, not a JSON document.
        self.assertNotIn("application/json", response["Content-Type"])

    def test_the_redirect_page_shows_the_success_message(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            response = self.post(3)
        page = self.client.get(response["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Forecast published")
        self.assertContains(page, "3 month(s)")
        self.assertContains(page, "current forecast")

    def test_three_month_horizon_publishes_only_the_next_three_months(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            response = self.post(3)
        run = current_forecast_run()
        months = sorted(set(run.months.values_list("month", flat=True)))
        expected = [add_months(TODAY, offset) for offset in (1, 2, 3)]
        self.assertEqual(months, expected)
        self.assertTrue(all(month > TODAY for month in months))
        self.assertIn(f"start={expected[0].isoformat()}", response["Location"])
        self.assertIn(f"end={expected[-1].isoformat()}", response["Location"])

    def test_failed_generation_redirects_back_with_an_error(self):
        previous = persist()
        validation = ValidationReport(start=HISTORY_START, end=HISTORY_END)
        validation.issues.append("synthetic failure")
        with mock.patch(
            "apps.forecast.views.generate_forecast",
            side_effect=ForecastDataError(validation),
        ):
            response = self.post(3)
        self.assertEqual(response.status_code, 303)
        self.assertIn("generation_error=", response["Location"])

        page = self.client.get(response["Location"])
        self.assertContains(page, "Forecast not generated")
        self.assertContains(page, "previously published forecast is unchanged")

        # The previous run stays current and nothing new was written.
        self.assertEqual(ForecastRun.objects.count(), 1)
        self.assertEqual(current_forecast_run().pk, previous.pk)
        self.assertTrue(current_forecast_run().is_current)

    def test_form_post_without_the_action_marker_generates_nothing(self):
        response = self.client.post(self.url, {"horizon": 3})
        self.assertEqual(response.status_code, 303)
        self.assertIn("generation_error=", response["Location"])
        self.assertEqual(ForecastRun.objects.count(), 0)

        page = self.client.get(response["Location"])
        self.assertContains(page, "Forecast not generated")

    def test_unsupported_horizon_redirects_back_with_an_error(self):
        response = self.post(9)
        self.assertEqual(response.status_code, 303)
        self.assertIn("generation_error=", response["Location"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_anonymous_form_post_redirects_to_the_login_page(self):
        self.client.logout()
        response = self.post(3)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_responder_form_post_redirects_to_the_dashboard(self):
        responder = make_user(email="resp@example.com", role=User.RoleChoices.RESPONDER)
        login(self.client, responder)
        response = self.post(3)
        self.assertEqual(response.status_code, 302)
        self.assertIn("dashboard", response["Location"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_get_on_the_endpoint_redirects_to_the_forecast_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.page_url, response["Location"])
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_the_success_message_is_dropped_when_the_page_is_reloaded(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            response = self.post(3)
        page = self.client.get(response["Location"])
        self.assertContains(page, "Forecast published")
        # Reloading the plain page again shows no message.
        plain = self.client.get(self.page_url)
        self.assertNotContains(plain, "Forecast published")


class PageConsistencyAfterGenerationTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_all_three_pages_and_the_export_show_the_new_run(self):
        previous = persist()
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            response = self.client.post(
                reverse("forecast:generate"),
                {"horizon": 6, "action": "generate"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200)
        run_id = response.json()["run_id"]

        forecast = self.client.get(reverse("forecast:prediction"))
        dashboard = self.client.get(reverse("dashboard:admin_index"))
        schedules = self.client.get(reverse("schedules:admin_calendar"))
        self.assertEqual(forecast.context["forecast"]["run_id"], run_id)
        self.assertEqual(dashboard.context["ai"]["run_id"], run_id)
        self.assertEqual(schedules.context["staffing"]["run_id"], run_id)

        export = self.client.get(reverse("forecast:export"))
        rows = list(csv.reader(StringIO(export.content.decode())))
        self.assertEqual(rows[0][0], "run_id")
        self.assertTrue(rows[1:])
        self.assertTrue(all(row[0] == str(run_id) for row in rows[1:]))
        self.assertNotIn(str(previous.run_id), [row[0] for row in rows[1:]])

        json_export = self.client.get(reverse("forecast:export") + "?format=json")
        self.assertEqual(json_export.json()["run_id"], run_id)
        self.assertEqual(json_export.json()["horizon_months"], 6)

    def test_a_form_post_publishes_one_run_shared_by_every_page(self):
        with mock.patch("apps.forecast.views.generate_forecast", side_effect=fake_generate):
            response = self.client.post(
                reverse("forecast:generate"), {"horizon": 3, "action": "generate"}
            )
        self.assertEqual(response.status_code, 303)
        run = current_forecast_run()
        forecast = self.client.get(reverse("forecast:prediction"))
        dashboard = self.client.get(reverse("dashboard:admin_index"))
        schedules = self.client.get(reverse("schedules:admin_calendar"))
        self.assertEqual(forecast.context["forecast"]["run_id"], run.run_id)
        self.assertEqual(dashboard.context["ai"]["run_id"], run.run_id)
        self.assertEqual(schedules.context["staffing"]["run_id"], run.run_id)
        self.assertEqual(ForecastRun.objects.count(), 1)


class FreshnessDisclosureTests(TestCase):
    def test_elapsed_window_is_flagged_as_stale(self):
        elapsed_months = month_span(add_months(TODAY, -2), TODAY)
        run = persist(
            result=make_result(
                months=elapsed_months,
                values={
                    "total": [200.0, 220.0, 240.0],
                    "morning": [100.0, 105.0, 110.0],
                    "afternoon": [70.0, 75.0, 80.0],
                    "night": [30.0, 40.0, 50.0],
                },
            )
        )
        payload = forecast_run_payload(run)
        self.assertTrue(payload["freshness"]["is_stale"])
        self.assertEqual(len(payload["freshness"]["elapsed_months"]), 3)
        self.assertTrue(payload["freshness"]["notes"])

    def test_future_window_is_not_stale_but_is_provisional(self):
        future_months = month_span(add_months(TODAY, 1), add_months(TODAY, 6))
        run = persist(
            result=make_result(
                months=future_months,
                values={
                    "total": [200.0, 220.0, 240.0, 260.0, 280.0, 300.0],
                    "morning": [100.0, 105.0, 110.0, 115.0, 120.0, 125.0],
                    "afternoon": [70.0, 75.0, 80.0, 85.0, 90.0, 95.0],
                    "night": [30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
                },
            )
        )
        payload = forecast_run_payload(run)
        self.assertFalse(payload["freshness"]["is_stale"])
        self.assertEqual(payload["freshness"]["elapsed_months"], [])
        # Training data ends before the current month, so the projection is
        # provisional even though the window is in the future.
        self.assertTrue(payload["freshness"]["is_provisional"])

    def test_forecast_page_shows_the_status_note_for_a_stale_run(self):
        elapsed_months = month_span(add_months(TODAY, -2), TODAY)
        persist(
            result=make_result(
                months=elapsed_months,
                values={
                    "total": [200.0, 220.0, 240.0],
                    "morning": [100.0, 105.0, 110.0],
                    "afternoon": [70.0, 75.0, 80.0],
                    "night": [30.0, 40.0, 50.0],
                },
            )
        )
        admin = make_user(email="admin2@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, admin)
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, "Forecast Status")
        self.assertContains(response, "have already passed")


class SelectorUiTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, self.admin)

    def test_page_offers_the_three_horizons_with_six_selected(self):
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, 'id="forecast-horizon"')
        self.assertContains(response, 'value="3"')
        self.assertContains(response, 'value="6"')
        self.assertContains(response, 'value="12"')
        self.assertContains(response, 'value="6" selected')
        self.assertContains(response, "Generate Forecast")

    def test_selector_is_present_without_any_run(self):
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, 'id="forecast-horizon"')
        self.assertContains(response, "Generate Forecast")

    def test_the_selector_defaults_to_the_published_run_horizon(self):
        # A published 3 month run keeps the selector on 3 months.
        persist(
            result=make_result(
                months=month_span(add_months(TODAY, 1), add_months(TODAY, 3)),
                values={
                    "total": [200.0, 210.0, 220.0],
                    "morning": [100.0, 105.0, 110.0],
                    "afternoon": [70.0, 75.0, 80.0],
                    "night": [30.0, 35.0, 40.0],
                },
            )
        )
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, 'value="3" selected')
        self.assertNotContains(response, 'value="6" selected')

    def test_the_selector_falls_back_to_six_for_an_unsupported_published_horizon(self):
        # The default persisted run holds two months, which is not a selectable
        # horizon, so the selector falls back to six.
        persist()
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, 'value="6" selected')

    def test_the_selector_never_submits_on_its_own(self):
        response = self.client.get(reverse("forecast:prediction"))
        html = response.content.decode()
        select_start = html.index('id="forecast-horizon"')
        select_block = html[select_start - 200:select_start + 200]
        self.assertNotIn("onchange", select_block)
        self.assertNotIn("oninput", select_block)

    def test_only_the_generate_button_carries_the_action_marker(self):
        response = self.client.get(reverse("forecast:prediction"))
        self.assertContains(response, 'name="action" value="generate"')
        self.assertContains(response, 'id="forecast-generate-button"')

    def test_loading_the_page_never_publishes_a_new_run(self):
        previous = persist()
        for _ in range(3):
            response = self.client.get(reverse("forecast:prediction"))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(ForecastRun.objects.count(), 1)
        self.assertEqual(current_forecast_run().pk, previous.pk)
        self.assertTrue(current_forecast_run().is_current)
