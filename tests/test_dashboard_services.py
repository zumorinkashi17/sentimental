"""Tests for dashboard services, including Phase 4 responder filtering."""

from datetime import date

from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboard import services
from tests.helpers import login, make_caller, make_session, make_shift, make_user


class HelperFunctionTests(TestCase):
    def test_percentages_sum_to_100(self):
        self.assertEqual(sum(services.percentages([1, 1, 1, 1])), 100)
        self.assertEqual(sum(services.percentages([5, 3, 2])), 100)

    def test_percentages_empty(self):
        self.assertEqual(services.percentages([]), [])

    def test_percentages_all_zero(self):
        self.assertEqual(services.percentages([0, 0, 0]), [0, 0, 0])

    def test_reason_category(self):
        self.assertEqual(services.reason_category("Suicidal thoughts"), "Suicidal Crisis")
        self.assertEqual(services.reason_category("relationship"), "Relationships")
        self.assertEqual(services.reason_category("financial"), "Career")
        self.assertEqual(services.reason_category(""), "Others")
        self.assertEqual(services.reason_category(None), "Others")

    def test_gender_bucket(self):
        self.assertEqual(services.gender_bucket("Male"), "Men")
        self.assertEqual(services.gender_bucket("F"), "Women")
        self.assertEqual(services.gender_bucket("LGBTQ+"), "LGBTQIA")
        self.assertIsNone(services.gender_bucket("Unknown"))
        self.assertIsNone(services.gender_bucket(None))

    def test_period_bounds_range_swaps_reversed_dates(self):
        start, end = services.period_bounds("range", date(2026, 3, 10), date(2026, 3, 1))
        self.assertEqual(start, date(2026, 3, 1))
        self.assertEqual(end, date(2026, 3, 10))

    def test_period_bounds_today(self):
        start, end = services.period_bounds("today")
        self.assertEqual(start, end)


class GaugeTests(TestCase):
    def test_gauge_for_single_queryset(self):
        user = make_user()
        shift = make_shift()
        caller = make_caller()
        make_session(user=user, caller=caller, shift=shift, risk="High")
        make_session(user=user, caller=caller, shift=shift, risk="Low")
        make_session(user=user, caller=caller, shift=shift, risk="Low")
        make_session(user=user, caller=caller, shift=shift, risk="Low")

        from apps.callers.models import CallSession

        gauge = services._gauge_for(CallSession.objects.all())
        self.assertEqual(gauge["total"], 4)
        self.assertEqual(gauge["high"], 1)
        self.assertEqual(gauge["pct"], 25)


class AdminContextFilterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.responder_a = make_user(email="a@example.com", first="Ana", last="A")
        self.responder_b = make_user(email="b@example.com", first="Ben", last="B")
        shift = make_shift()
        caller = make_caller(gender="Male")

        # All sessions live inside the explicit range window below.
        self.a_high = make_session(
            user=self.responder_a, caller=caller, shift=shift,
            on=date(2026, 1, 10), risk="High", reason="relationship",
        )
        make_session(
            user=self.responder_a, caller=caller, shift=shift,
            on=date(2026, 1, 11), risk="Low",
        )
        make_session(
            user=self.responder_b, caller=caller, shift=shift,
            on=date(2026, 1, 12), risk="High",
        )

    def _admin_request(self, **params):
        query = {"period": "range", "start": "2026-01-01", "end": "2026-01-31"}
        query.update(params)
        return self.factory.get("/dashboard/admin/index/", query)

    def test_unfiltered_totals(self):
        ctx = services.admin_context(self._admin_request())
        self.assertEqual(ctx["total"], 3)
        self.assertEqual(ctx["high"], 2)

    def test_responder_filter_scopes_kpis(self):
        ctx = services.admin_context(self._admin_request(responder=str(self.responder_a.user_id)))
        self.assertEqual(ctx["current_responder"], str(self.responder_a.user_id))
        self.assertEqual(ctx["total"], 2)
        self.assertEqual(ctx["high"], 1)

    def test_responder_filter_scopes_alerts(self):
        ctx = services.admin_context(self._admin_request(responder=str(self.responder_a.user_id)))
        for alert in ctx["alerts"]:
            self.assertEqual(alert["handled_by"], str(self.responder_a))
        self.assertEqual(ctx["alerts"][0]["id"], self.a_high.session_id)

    def test_responder_counts_stay_global(self):
        ctx = services.admin_context(self._admin_request(responder=str(self.responder_a.user_id)))
        # Both responders are counted even while the KPI cards are scoped.
        self.assertEqual(ctx["total_responders"], 2)

    def test_analytics_block_present(self):
        ctx = services.admin_context(self._admin_request())
        for key in ("reasons", "reasons_total", "callers", "callers_total", "gauge"):
            self.assertIn(key, ctx)
        self.assertEqual(ctx["gauge"]["total"], 3)
        self.assertEqual(ctx["gauge"]["high"], 2)


class AdminAiCardTests(TestCase):
    """The AI Volume Prediction card reads the shared persisted forecast run."""

    def setUp(self):
        self.factory = RequestFactory()

    def _admin_context(self):
        request = self.factory.get(
            "/dashboard/admin/index/",
            {"period": "range", "start": "2026-01-01", "end": "2026-01-31"},
        )
        return services.admin_context(request)

    def _persist(self, **kwargs):
        from tests.test_forecast_persistence import make_result, persist

        return persist(make_result(**kwargs))

    def test_card_uses_current_persisted_run(self):
        self._persist()
        ai = self._admin_context()["ai"]
        self.assertTrue(ai["available"])
        self.assertEqual(ai["period"], "May 2026")
        self.assertEqual(ai["predicted"], 200)
        self.assertEqual(ai["status"], "200 calls")
        self.assertTrue(ai["generated_label"].startswith("Forecast generated"))

    def test_card_distinguishes_forecast_from_recorded_calls(self):
        self._persist()
        message = self._admin_context()["ai"]["message"]
        self.assertIn("forecast", message)
        self.assertIn("not a count of calls already received", message)

    def test_card_matches_shared_run_payload(self):
        self._persist()
        from apps.forecast.services import current_forecast_run, forecast_run_payload

        payload = forecast_run_payload(current_forecast_run())
        first = payload["months"][0]
        ai = self._admin_context()["ai"]
        self.assertEqual(ai["predicted"], int(round(first["yhat"])))
        # The label shows the same moment as the stored UTC value, in the
        # application's timezone.
        self.assertIn(payload["generated_at"][:4], ai["generated_label"])
        self.assertTrue(ai["generated_label"].endswith("PHT"))

    def test_card_flags_leading_shift_uncertainty(self):
        # Morning and Afternoon 80% intervals overlap -> provisional.
        self._persist(values={
            "total": [200.0, 220.0],
            "morning": [100.0, 105.0],
            "afternoon": [98.0, 102.0],
            "night": [25.0, 30.0],
        })
        ai = self._admin_context()["ai"]
        self.assertTrue(ai["leading_shift"].startswith("Morning Shift"))
        self.assertTrue(ai["uncertain"])
        self.assertTrue(ai["uncertainty_note"])

    def test_card_leading_shift_confident_when_gap_is_clear(self):
        self._persist(values={
            "total": [300.0, 320.0],
            "morning": [200.0, 210.0],
            "afternoon": [50.0, 52.0],
            "night": [20.0, 21.0],
        })
        ai = self._admin_context()["ai"]
        self.assertTrue(ai["leading_shift"].startswith("Morning Shift"))
        self.assertFalse(ai["uncertain"])
        self.assertIsNone(ai["uncertainty_note"])

    def test_card_fallback_without_current_run(self):
        ai = self._admin_context()["ai"]
        self.assertFalse(ai["available"])
        self.assertEqual(ai["status"], "Forecast Unavailable")
        self.assertIn("No forecast run", ai["message"])
        self.assertIsNone(ai["leading_shift"])

    def test_card_ignores_non_current_run(self):
        from tests.test_forecast_persistence import persist

        persist(is_current=False)
        ai = self._admin_context()["ai"]
        self.assertFalse(ai["available"])


class AdminAiCardRenderTests(TestCase):
    """The forecast card renders in the real admin dashboard template."""

    def setUp(self):
        self.admin = make_user(email="admin@example.com", role="Admin", first="Admin")
        login(self.client, self.admin)

    def _persist(self, **kwargs):
        from tests.test_forecast_persistence import make_result, persist

        return persist(make_result(**kwargs))

    def test_dashboard_renders_forecast_values_and_metadata(self):
        self._persist()
        resp = self.client.get(reverse("dashboard:admin_index"))
        self.assertContains(resp, "Expected Call Volume")
        self.assertContains(resp, "200 calls")
        self.assertContains(resp, "not a count of calls already received")
        self.assertContains(resp, "Forecast generated")

    def test_dashboard_renders_uncertainty_warning(self):
        self._persist(values={
            "total": [200.0, 220.0],
            "morning": [100.0, 105.0],
            "afternoon": [98.0, 102.0],
            "night": [25.0, 30.0],
        })
        resp = self.client.get(reverse("dashboard:admin_index"))
        self.assertContains(resp, "Expected busiest shift: Morning Shift")
        self.assertContains(resp, "Uncertain")

    def test_dashboard_renders_fallback_without_run(self):
        resp = self.client.get(reverse("dashboard:admin_index"))
        self.assertContains(resp, "Forecast Unavailable")

    def test_existing_kpi_cards_still_render(self):
        self._persist()
        resp = self.client.get(reverse("dashboard:admin_index"))
        self.assertContains(resp, "Total Calls")
        self.assertContains(resp, "High Risk Interventions")
        self.assertContains(resp, "Active Responders")


class ResponderOptionsTests(TestCase):
    def test_only_responders_with_sessions_are_listed(self):
        with_sessions = make_user(email="has@example.com", first="Has", last="Calls")
        without = make_user(email="no@example.com", first="No", last="Calls")
        make_session(user=with_sessions)

        options = list(services.responder_options())
        self.assertIn(with_sessions, options)
        self.assertNotIn(without, options)


class ResponderContextTests(TestCase):
    def test_context_keys_and_totals(self):
        factory = RequestFactory()
        user = make_user(email="r@example.com", first="Rey")
        caller_m = make_caller(gender="Male")
        caller_f = make_caller(gender="Female")
        shift = make_shift()
        make_session(user=user, caller=caller_m, shift=shift, on=date(2026, 1, 6), reason="relationship")
        make_session(user=user, caller=caller_f, shift=shift, on=date(2026, 1, 7), reason="suicidal")

        request = factory.get("/dashboard/", {"period": "range", "start": "2026-01-01", "end": "2026-01-31"})
        ctx = services.responder_context(request, user)
        self.assertEqual(ctx["greeting_name"], "Rey")
        self.assertEqual(ctx["reasons_total"], 2)
        self.assertEqual(ctx["callers_total"], 2)
        self.assertIn("gauge", ctx)
        self.assertIn("volume", ctx)
