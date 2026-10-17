"""Tests for views: reports, documentation (P3 fixes), accounts manage."""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.core.paginator import Paginator

from apps.accounts.models import User
from apps.reports.models import Report
from tests.helpers import make_report, make_session, make_shift, make_user, make_caller, login


class ReportsViewTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role="Admin", first="Admin")
        self.client = login(self.client, self.admin)

    def test_generate_view_reports_years_are_strings_and_sorted(self):
        # One report with " | " and a 2024 range (target_year becomes str later)
        make_report(self.admin, title="A | 2024-01 to 2024-03")
        # One report with title without " | " -> target_year is generated_date.year (int in context extraction)
        make_report(self.admin, title="B", generated=date(2025, 5, 1))

        resp = self.client.get(reverse("reports:generate"))
        self.assertEqual(resp.status_code, 200)
        years = resp.context["report_years"]
        self.assertIsInstance(years, list)
        for y in years:
            self.assertIsInstance(y, str)
        # Expect 2025, 2024 (descending)
        self.assertEqual(years[:2], ["2025", "2024"])

    def test_generate_view_filters_by_selected_year(self):
        make_report(self.admin, title="A | 2024-01 to 2024-03")
        make_report(self.admin, title="B | 2025-01 to 2025-03")

        resp = self.client.get(reverse("reports:generate") + "?year=2024")
        self.assertEqual(resp.status_code, 200)
        reports_in_context = resp.context["reports"]
        self.assertEqual(len(reports_in_context), 1)

    def test_generate_view_requires_admin(self):
        client = login(self.client, make_user(email="r@example.com", role="Responder"))
        resp = client.get(reverse("reports:generate"))
        self.assertEqual(resp.status_code, 302)  # redirected


class DocumentationViewTests(TestCase):
    def setUp(self):
        self.user = make_user(email="r@example.com", role="Responder", first="R")
        self.client = login(self.client, self.user)
        self.shift = make_shift()

    def test_master_history_highlight_page_jump(self):
        DEFAULT_PAGE_SIZE = 20
        caller = make_caller()
        # Create 25 sessions with dates so ordering is predictable (desc by date)
        sessions = []
        for i in range(25):
            s = make_session(
                user=self.user,
                caller=caller,
                shift=self.shift,
                on=date(2026, 1, 1) + timedelta(days=i),
                reason="test",
            )
            sessions.append(s)
        # sessions[0] has on=2026-01-01 (i=0), sessions[24] has i=24 (newest)
        sessions.sort(key=lambda x: (x.session_call_date, x.session_time_called), reverse=True)
        # Highlight the session at position 22 in the ordered list (0-based) -> index 22, page 2 (22//20+1)
        highlight_id = sessions[22].session_id
        resp = self.client.get(reverse("documentation:master_history") + f"?highlight={highlight_id}")
        self.assertEqual(resp.status_code, 200)
        page_obj = resp.context["page_obj"]
        self.assertEqual(page_obj.number, 2)

    def test_history_view_paginates(self):
        caller = make_caller()
        for i in range(25):
            make_session(user=self.user, caller=caller, shift=self.shift, on=date(2026, 2, 1) + timedelta(days=i))
        resp = self.client.get(reverse("documentation:history"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["page_obj"].paginator.num_pages, 2)


class AccountsManageTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role="Admin")
        self.client = login(self.client, self.admin)

    def test_manage_users_excludes_current_user_and_paginates(self):
        for i in range(25):
            make_user(email=f"u{i}@example.com", role="Responder")
        resp = self.client.get(reverse("accounts:manage"))
        self.assertEqual(resp.status_code, 200)
        users_list = resp.context["users"]
        # 25 created + 1 admin = 26 total; admin excluded -> 25 in queryset paginated
        self.assertEqual(len(users_list), 20)  # first page
        page_obj = resp.context["page_obj"]
        self.assertEqual(page_obj.paginator.num_pages, 2)
        for u in users_list:
            self.assertNotEqual(u.user_id, self.admin.user_id)

    def test_manage_users_search_filters(self):
        make_user(email="alice@example.com", first="Alice", last="A", role="Responder")
        make_user(email="bob@example.com", first="Bob", last="B", role="Responder")
        resp = self.client.get(reverse("accounts:manage") + "?search=alice")
        self.assertEqual(resp.status_code, 200)
        users_list = resp.context["users"]
        self.assertEqual(len(users_list), 1)
        self.assertEqual(users_list[0].user_first_name, "Alice")

    def test_manage_users_status_filter(self):
        make_user(email="active@example.com", status="Active", role="Responder")
        make_user(email="inactive@example.com", status="Inactive", role="Responder")
        resp = self.client.get(reverse("accounts:manage") + "?status=inactive")
        self.assertEqual(resp.status_code, 200)
        users_list = resp.context["users"]
        self.assertEqual(len(users_list), 1)
        self.assertEqual(users_list[0].user_status, "Inactive")

    def test_manage_users_requires_admin(self):
        client = login(self.client, make_user(email="r@example.com", role="Responder"))
        resp = client.get(reverse("accounts:manage"))
        self.assertEqual(resp.status_code, 302)
