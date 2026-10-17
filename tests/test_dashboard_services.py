"""Tests for dashboard services, including Phase 4 responder filtering."""

from datetime import date

from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.dashboard import services
from tests.helpers import make_caller, make_session, make_shift, make_user


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
