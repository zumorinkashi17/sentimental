"""Tests for notifications (Phase 4 / 6)."""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import DayOffRequest
from tests.helpers import make_day_off, make_user, login


class NotificationTests(TestCase):
    def test_admin_receives_pending_dayoffs(self):
        admin = make_user(email="admin@example.com", role="Admin", first="Admin")
        client = login(self.client, admin)

        responder = make_user(email="res@example.com", first="Res")
        make_day_off(responder, status=DayOffRequest.StatusChoices.PENDING, reason="Exam", on=__import__("datetime").date(2026, 3, 1))

        resp = client.get(reverse("notifications:get_notifications"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["notifications"]), 1)
        self.assertEqual(data["notifications"][0]["name"], "Res User")
        self.assertEqual(data["notifications"][0]["reason"], "Exam")

    def test_responder_receives_processed_unread_notifications(self):
        responder = make_user(email="res@example.com", first="Res")
        client = login(self.client, responder)
        admin = make_user(email="admin@example.com", role="Admin")

        make_day_off(responder, status=DayOffRequest.StatusChoices.APPROVED, is_read=False, reason="Sick")

        resp = client.get(reverse("notifications:get_notifications"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["notifications"]), 1)
        self.assertEqual(data["notifications"][0]["status"], "Approved")

    def test_mark_read_clears_responder_notifications(self):
        responder = make_user(email="res@example.com")
        client = login(self.client, responder)
        make_day_off(responder, status=DayOffRequest.StatusChoices.DENIED, is_read=False)

        resp = client.post(reverse("notifications:mark_read"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        resp = client.get(reverse("notifications:get_notifications"))
        self.assertEqual(len(resp.json()["notifications"]), 0)

    def test_guest_or_unknown_returns_empty(self):
        resp = self.client.get(reverse("notifications:get_notifications"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["notifications"], [])

        r = self.client.post(reverse("notifications:mark_read"))
        # Missing user_id -> returns error 401 as per view.
        self.assertEqual(r.status_code, 401)
