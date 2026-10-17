"""Cross-cutting tests: smoke checks, base template single CSS link."""

from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from tests.helpers import make_user, login


URLS_NO_ARGS = [
    "accounts:login",
    "accounts:manage",
    "accounts:profile",
    "dashboard:index",
    "dashboard:admin_index",
    "dashboard:dashboard_general",
    "dashboard:call_logs",
    "dashboard:call_logs_admin",
    "dashboard:dongle_config",
    "dashboard:dongle_engine",
    "callers:list",
    "callers:database",
    "callers:call_setup",
    "callers:transcribe",
    "callers:save_session",
    "documentation:history",
    "documentation:master_history",
    "documentation:admin_history",
    "forecast:prediction",
    "referrals:directory",
    "referrals:manage",
    "schedules:calendar",
    "schedules:admin_calendar",
    "schedules:submit_dayoff_request",
    "schedules:add_shift",
    "schedules:save_schedule",
    "schedules:update_schedule_days_off",
    "schedules:update_dayoff_status",
    "heatmap:map",
    "reports:generate",
    "notifications:get_notifications",
    "notifications:mark_read",
]

URLS_WITH_ARGS = [
    ("reports:export_pdf", {"report_id": 1}),
    ("schedules:api_user_schedule", {"user_id": 1}),
    ("accounts:get_responder", {"user_id": 1}),
    ("accounts:edit_responder", {"user_id": 1}),
]


class SmokeTests(TestCase):
    def test_urls_reverse_without_args(self):
        for name in URLS_NO_ARGS:
            with self.subTest(url=name):
                # Reverse should not raise
                try:
                    url = reverse(name)
                except Exception as exc:
                    self.fail(f"reverse({name}) failed: {exc}")
                self.assertIsInstance(url, str)

    def test_urls_reverse_with_args(self):
        for name, kwargs in URLS_WITH_ARGS:
            with self.subTest(url=name):
                url = reverse(name, kwargs=kwargs)
                self.assertIsInstance(url, str)

    def test_base_html_has_single_global_css_link(self):
        base = Path(__file__).resolve().parents[1] / "templates" / "base.html"
        self.assertTrue(base.exists(), f"Missing {base}")
        content = base.read_text(encoding="utf-8")
        # Count references to global.css
        count = content.count("css/global.css")
        self.assertEqual(count, 1, "Expected exactly one global.css link in base.html")

    def test_dashboard_pages_render_with_sessions(self):
        admin = make_user(email="admin@example.com", role="Admin", first="Admin")
        client = login(self.client, admin)
        resp = client.get(reverse("dashboard:admin_index"))
        self.assertEqual(resp.status_code, 200)

        resp = client.get(reverse("accounts:manage"))
        self.assertEqual(resp.status_code, 200)

        responder = make_user(email="r@example.com", role="Responder", first="Res")
        client = login(self.client, responder)
        resp = client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 200)
        resp = client.get(reverse("callers:list"))
        self.assertEqual(resp.status_code, 200)
        resp = client.get(reverse("callers:database"))
        self.assertEqual(resp.status_code, 200)
        resp = client.get(reverse("documentation:history"))
        self.assertEqual(resp.status_code, 200)
        resp = client.get(reverse("documentation:master_history"))
        self.assertEqual(resp.status_code, 200)
        resp = client.get(reverse("reports:generate"))  # admin-only route, responder should redirect
        self.assertEqual(resp.status_code, 302)

        admin2 = make_user(email="admin2@example.com", role="Admin", first="A2")
        client = login(self.client, admin2)
        resp = client.get(reverse("reports:generate"))
        self.assertEqual(resp.status_code, 200)
