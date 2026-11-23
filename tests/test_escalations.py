"""Tests for MHP roles and the caller escalation workflow."""

import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboard.views import _get_session_user
from apps.escalations import services
from apps.escalations.models import CallerEscalation, EscalationAssessment, EscalationEvent
from tests.helpers import (
    login,
    make_assessment,
    make_escalation,
    make_escalation_event,
    make_session,
    make_user,
)


class RoleFoundationTests(TestCase):
    def test_mhp_role_is_registered(self):
        self.assertIn(User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL, User.RoleChoices.values)
        self.assertEqual(User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL, "Mental Health Professional")

    def test_mhp_is_routed_to_professional_dashboard(self):
        mhp = make_user(
            email="mhp-route@example.com",
            role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
            first="Mental",
            last="Professional",
        )
        login(self.client, mhp)

        response = self.client.get(reverse("dashboard:index"))
        self.assertRedirects(response, reverse("dashboard:professional_index"))

        response = self.client.get(reverse("dashboard:professional_index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mental Health Professional Dashboard")
        self.assertContains(response, "Recent escalations")

    def test_get_session_user_maps_wrong_role_to_own_home(self):
        mhp = make_user(
            email="mhp-wrong-role@example.com",
            role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
        )
        self.client = login(self.client, mhp)
        request = self.client.get(reverse("escalations:queue")).wsgi_request
        request.session = self.client.session

        user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
        self.assertIsNone(user)
        self.assertEqual(redirect_response.url, reverse("dashboard:professional_index"))

    def test_admin_can_add_mhp_account(self):
        admin = make_user(email="admin-add@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, admin)

        with patch("apps.accounts.views.send_mail") as send_mail:
            response = self.client.post(
                reverse("accounts:add_responder"),
                {
                    "email": "new-mhp@example.com",
                    "user_role": User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)["success"])
        user = User.objects.get(user_email="new-mhp@example.com")
        self.assertEqual(user.user_role, User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL)
        self.assertEqual(user.user_status, User.StatusChoices.INACTIVE)
        self.assertTrue(send_mail.called)

    def test_invalid_role_is_rejected(self):
        admin = make_user(email="admin-invalid@example.com", role=User.RoleChoices.ADMIN)
        login(self.client, admin)

        response = self.client.post(
            reverse("accounts:add_responder"),
            {"email": "bad-role@example.com", "user_role": "Superuser"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(user_email="bad-role@example.com").exists())

    def test_non_admin_cannot_add_accounts(self):
        responder = make_user(email="responder-add@example.com", role=User.RoleChoices.RESPONDER)
        login(self.client, responder)

        response = self.client.post(
            reverse("accounts:add_responder"),
            {
                "email": "nope@example.com",
                "user_role": User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(user_email="nope@example.com").exists())


class EscalationServiceTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="escalation-admin@example.com", role=User.RoleChoices.ADMIN)
        self.responder = make_user(email="escalation-responder@example.com")
        self.other_responder = make_user(email="escalation-other@example.com")
        self.mhp = make_user(
            email="escalation-mhp@example.com",
            role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
        )
        self.other_mhp = make_user(
            email="escalation-other-mhp@example.com",
            role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
        )
        self.session = make_session(user=self.responder)

    def test_create_escalation_starts_pending_and_records_event(self):
        escalation = services.create_escalation(
            session=self.session,
            requested_by=self.responder,
            observations="Caller needs professional assessment.",
            urgency=CallerEscalation.UrgencyChoices.PRIORITY,
        )

        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.PENDING)
        self.assertIsNone(escalation.assigned_to)
        self.assertEqual(escalation.events.count(), 1)
        event = escalation.events.first()
        self.assertEqual(event.event_type, EscalationEvent.EventTypeChoices.CREATED)
        self.assertEqual(event.to_status, CallerEscalation.StatusChoices.PENDING)

    def test_create_escalation_with_assignment_starts_assigned(self):
        escalation = services.create_escalation(
            session=self.session,
            requested_by=self.admin,
            observations="Assessed as urgent.",
            urgency=CallerEscalation.UrgencyChoices.URGENT,
            assigned_to=self.mhp,
        )

        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.ASSIGNED)
        self.assertEqual(escalation.assigned_to, self.mhp)
        self.assertIsNotNone(escalation.assigned_at)
        self.assertEqual(
            [event.event_type for event in escalation.events.all()],
            [EscalationEvent.EventTypeChoices.CREATED, EscalationEvent.EventTypeChoices.ASSIGNED],
        )

    def test_cannot_create_two_active_escalations_for_one_session(self):
        services.create_escalation(
            session=self.session,
            requested_by=self.responder,
            observations="First escalation.",
            urgency=CallerEscalation.UrgencyChoices.ROUTINE,
        )

        with self.assertRaises(services.EscalationConflictError):
            services.create_escalation(
                session=self.session,
                requested_by=self.responder,
                observations="Duplicate escalation.",
                urgency=CallerEscalation.UrgencyChoices.ROUTINE,
            )

    def test_mhp_cannot_create_escalation(self):
        with self.assertRaises(services.EscalationPermissionError):
            services.create_escalation(
                session=self.session,
                requested_by=self.mhp,
                observations="MHP attempted to escalate.",
                urgency=CallerEscalation.UrgencyChoices.ROUTINE,
            )

    def test_visibility_is_scoped_by_role(self):
        owned = make_escalation(session=self.session, requested_by=self.responder)
        assigned = make_escalation(
            session=make_session(user=self.other_responder),
            requested_by=self.other_responder,
            assigned_to=self.mhp,
            status=CallerEscalation.StatusChoices.ASSIGNED,
        )

        self.assertEqual(set(services.visible_escalations(self.admin)), {owned, assigned})
        self.assertEqual(list(services.visible_escalations(self.responder)), [owned])
        self.assertEqual(list(services.visible_escalations(self.other_mhp)), [])
        self.assertEqual(list(services.visible_escalations(self.mhp)), [assigned])

    def test_counts_use_template_safe_keys(self):
        make_escalation(session=self.session, requested_by=self.responder)
        counts = services.escalation_counts(self.responder)

        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["active"], 1)
        self.assertEqual(counts["all"], 1)
        self.assertEqual(counts["completed"], 0)

    def test_get_escalation_for_user_denies_unrelated_responder(self):
        escalation = make_escalation(session=self.session, requested_by=self.responder)

        self.assertEqual(services.get_escalation_for_user(escalation.pk, self.responder), escalation)
        with self.assertRaises(services.EscalationPermissionError):
            services.get_escalation_for_user(escalation.pk, self.other_responder)

    def test_full_workflow_records_assessment_and_all_events(self):
        escalation = services.create_escalation(
            session=self.session,
            requested_by=self.responder,
            observations="Escalation for full workflow.",
            urgency=CallerEscalation.UrgencyChoices.ROUTINE,
        )

        services.assign_escalation(escalation, self.admin, self.mhp)
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.ASSIGNED)

        services.acknowledge_escalation(escalation, self.mhp)
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.UNDER_REVIEW)

        services.request_info(escalation, self.mhp, "Please confirm the caller's earlier risk flags.")
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.NEEDS_INFO)

        services.provide_info(escalation, self.responder, "Confirmed two prior high-risk contacts.")
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.UNDER_REVIEW)

        escalation, assessment = services.complete_escalation(
            escalation,
            self.mhp,
            findings="No immediate safety concern after review.",
            recommendations="Continue supportive counseling.",
            follow_up=EscalationAssessment.FollowUpChoices.SCHEDULED_FOLLOW_UP,
        )
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.COMPLETED)
        self.assertIsNotNone(escalation.resolved_at)
        self.assertEqual(assessment.assessed_by, self.mhp)
        self.assertEqual(escalation.assessments.count(), 1)

        self.assertEqual(
            list(escalation.events.values_list("event_type", flat=True)),
            [
                EscalationEvent.EventTypeChoices.CREATED,
                EscalationEvent.EventTypeChoices.ASSIGNED,
                EscalationEvent.EventTypeChoices.ACKNOWLEDGED,
                EscalationEvent.EventTypeChoices.INFO_REQUESTED,
                EscalationEvent.EventTypeChoices.INFO_PROVIDED,
                EscalationEvent.EventTypeChoices.ASSESSED,
            ],
        )

    def test_invalid_transition_is_rejected(self):
        escalation = make_escalation(
            session=self.session,
            requested_by=self.responder,
            assigned_to=self.mhp,
            status=CallerEscalation.StatusChoices.ASSIGNED,
        )

        with self.assertRaises(services.InvalidTransitionError):
            services.complete_escalation(
                escalation,
                self.mhp,
                findings="Findings",
                recommendations="Recommendations",
                follow_up=EscalationAssessment.FollowUpChoices.NO_FURTHER_ACTION,
            )

    def test_only_assigned_mhp_can_acknowledge(self):
        escalation = make_escalation(
            session=self.session,
            requested_by=self.responder,
            assigned_to=self.mhp,
            status=CallerEscalation.StatusChoices.ASSIGNED,
        )

        with self.assertRaises(services.EscalationPermissionError):
            services.acknowledge_escalation(escalation, self.other_mhp)

    def test_cancel_escalation_records_reason(self):
        escalation = make_escalation(session=self.session, requested_by=self.responder)

        services.cancel_escalation(escalation, self.responder, note="Duplicate request.")

        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.CANCELLED)
        self.assertIsNotNone(escalation.resolved_at)
        self.assertEqual(escalation.events.first().note, "Duplicate request.")

    def test_mask_phone_keeps_only_last_four_digits(self):
        self.assertEqual(services.mask_phone("0917 123 4567"), "***-***-4567")
        self.assertEqual(services.mask_phone("123"), "***")
        self.assertEqual(services.mask_phone(None), "")

    def test_display_id_is_human_readable(self):
        escalation = make_escalation(session=self.session, requested_by=self.responder)

        self.assertRegex(escalation.display_id, r"^ESC-\d{4}-\d{4}$")
        self.assertNotEqual(escalation.display_id, str(escalation.escalation_id))
        self.assertIn(escalation.display_id, str(escalation))

    def test_case_context_includes_session_caller_and_phone(self):
        self.session.caller.caller_number = "09171234567"
        self.session.caller.save()
        escalation = make_escalation(session=self.session, requested_by=self.responder)

        context = services.get_case_context(escalation)

        self.assertEqual(context["escalation"], escalation)
        self.assertEqual(context["session"], self.session)
        self.assertEqual(context["caller"], self.session.caller)
        self.assertEqual(context["masked_phone"], "***-***-4567")
        self.assertIn("transcripts", context)
        self.assertIn("referral", context)
        self.assertIn("prior_sessions", context)


class EscalationViewTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="view-admin@example.com", role=User.RoleChoices.ADMIN)
        self.responder = make_user(email="view-responder@example.com", first="Responder")
        self.other_responder = make_user(email="view-other@example.com", first="Other")
        self.mhp = make_user(
            email="view-mhp@example.com",
            role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
            first="Assigned",
            last="Professional",
        )
        self.session = make_session(user=self.responder)

    def test_queue_is_scoped_by_role(self):
        own = make_escalation(session=self.session, requested_by=self.responder)
        assigned = make_escalation(
            session=make_session(user=self.other_responder),
            requested_by=self.other_responder,
            assigned_to=self.mhp,
            status=CallerEscalation.StatusChoices.ASSIGNED,
        )

        login(self.client, self.responder)
        response = self.client.get(reverse("escalations:queue"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(own, response.context["page_obj"].object_list)
        self.assertNotIn(assigned, response.context["page_obj"].object_list)

        login(self.client, self.mhp)
        response = self.client.get(reverse("escalations:queue"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(assigned, response.context["page_obj"].object_list)
        self.assertNotIn(own, response.context["page_obj"].object_list)

        login(self.client, self.admin)
        response = self.client.get(reverse("escalations:queue"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["page_obj"].object_list), {own, assigned})

    def test_new_escalation_post_creates_escalation(self):
        login(self.client, self.responder)

        response = self.client.post(
            reverse("escalations:new") + f"?session_id={self.session.session_id}",
            {
                "session_id": self.session.session_id,
                "urgency": CallerEscalation.UrgencyChoices.ROUTINE,
                "observations": "Escalated from the documentation page.",
            },
        )

        escalation = CallerEscalation.objects.get()
        self.assertRedirects(
            response,
            reverse("escalations:detail", args=[escalation.escalation_id]),
        )
        self.assertEqual(escalation.requested_by, self.responder)
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.PENDING)

    def test_responder_can_select_mhp_when_creating_escalation(self):
        login(self.client, self.responder)

        response = self.client.post(
            reverse("escalations:new") + f"?session_id={self.session.session_id}",
            {
                "session_id": self.session.session_id,
                "urgency": CallerEscalation.UrgencyChoices.PRIORITY,
                "observations": "Escalated directly to the available professional.",
                "assigned_to": self.mhp.user_id,
            },
        )

        escalation = CallerEscalation.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(escalation.assigned_to, self.mhp)
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.ASSIGNED)

    def test_new_escalation_form_offers_mhp_choice_to_responder(self):
        login(self.client, self.responder)

        response = self.client.get(
            reverse("escalations:new") + f"?session_id={self.session.session_id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_assigned_to"')
        self.assertContains(response, "Assign to mental health professional (optional)")

    def test_mhp_cannot_create_escalation(self):
        login(self.client, self.mhp)

        response = self.client.get(
            reverse("escalations:new") + f"?session_id={self.session.session_id}"
        )

        self.assertRedirects(response, reverse("dashboard:professional_index"))
        self.assertFalse(CallerEscalation.objects.exists())

    def test_detail_denies_unrelated_responder(self):
        escalation = make_escalation(session=self.session, requested_by=self.responder)
        login(self.client, self.other_responder)

        response = self.client.get(
            reverse("escalations:detail", args=[escalation.escalation_id])
        )

        self.assertRedirects(response, reverse("escalations:queue"))

    def test_admin_can_assign_through_detail_view(self):
        escalation = make_escalation(session=self.session, requested_by=self.responder)
        login(self.client, self.admin)

        response = self.client.post(
            reverse("escalations:assign", args=[escalation.escalation_id]),
            {"assigned_to": self.mhp.user_id},
        )

        self.assertRedirects(
            response,
            reverse("escalations:detail", args=[escalation.escalation_id]),
        )
        escalation.refresh_from_db()
        self.assertEqual(escalation.assigned_to, self.mhp)
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.ASSIGNED)

    def test_assignment_view_rejects_inactive_mhp(self):
        escalation = make_escalation(session=self.session, requested_by=self.responder)
        inactive_mhp = make_user(
            email="inactive-mhp@example.com",
            role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
            status=User.StatusChoices.INACTIVE,
        )
        login(self.client, self.admin)

        response = self.client.post(
            reverse("escalations:assign", args=[escalation.escalation_id]),
            {"assigned_to": inactive_mhp.user_id},
        )

        self.assertEqual(response.status_code, 302)
        escalation.refresh_from_db()
        self.assertIsNone(escalation.assigned_to)
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.PENDING)

    def test_mhp_workflow_through_views(self):
        escalation = services.create_escalation(
            session=self.session,
            requested_by=self.responder,
            observations="Escalated for professional review.",
            urgency=CallerEscalation.UrgencyChoices.ROUTINE,
            assigned_to=self.mhp,
        )
        login(self.client, self.mhp)

        response = self.client.post(
            reverse("escalations:acknowledge", args=[escalation.escalation_id])
        )
        self.assertEqual(response.status_code, 302)
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.UNDER_REVIEW)

        response = self.client.post(
            reverse("escalations:request_info", args=[escalation.escalation_id]),
            {"note": "Please provide earlier risk history."},
        )
        self.assertEqual(response.status_code, 302)
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.NEEDS_INFO)

        login(self.client, self.responder)
        response = self.client.post(
            reverse("escalations:provide_info", args=[escalation.escalation_id]),
            {"note": "Two prior high-risk contacts confirmed."},
        )
        self.assertEqual(response.status_code, 302)
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.UNDER_REVIEW)

        login(self.client, self.mhp)
        response = self.client.post(
            reverse("escalations:complete", args=[escalation.escalation_id]),
            {
                "findings": "Review complete.",
                "recommendations": "Continue current support plan.",
                "follow_up": EscalationAssessment.FollowUpChoices.NO_FURTHER_ACTION,
            },
        )
        self.assertEqual(response.status_code, 302)
        escalation.refresh_from_db()
        self.assertEqual(escalation.status, CallerEscalation.StatusChoices.COMPLETED)
        self.assertEqual(escalation.assessments.count(), 1)

        response = self.client.get(
            reverse("escalations:detail", args=[escalation.escalation_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, escalation.display_id)
        self.assertContains(response, "Review complete.")
        self.assertContains(response, "No further action")

    def test_professional_dashboard_shows_assigned_escalation(self):
        escalation = make_escalation(
            session=self.session,
            requested_by=self.responder,
            assigned_to=self.mhp,
            status=CallerEscalation.StatusChoices.ASSIGNED,
        )
        login(self.client, self.mhp)

        response = self.client.get(reverse("dashboard:professional_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["counts"]["assigned"], 1)
        self.assertIn(escalation, response.context["escalations"])
        self.assertContains(response, escalation.session.session_id)
        self.assertContains(response, escalation.display_id)

    def test_documentation_history_exposes_escalate_link(self):
        login(self.client, self.responder)

        response = self.client.get(reverse("documentation:master_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="modal-escalate-link"')
        self.assertContains(response, reverse("escalations:new"))

    def test_mhp_profile_shows_escalation_count_instead_of_calls_handled(self):
        make_escalation(
            session=self.session,
            requested_by=self.responder,
            assigned_to=self.mhp,
            status=CallerEscalation.StatusChoices.ASSIGNED,
        )
        login(self.client, self.mhp)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["escalations_count"], 1)
        self.assertContains(response, "Escalations")
        self.assertNotContains(response, "Calls Handled")

    def test_persistent_panel_is_hidden_for_mhp_but_visible_for_responders(self):
        login(self.client, self.mhp)
        response = self.client.get(reverse("escalations:queue"))
        self.assertNotContains(response, 'id="persistent-panel"')

        login(self.client, self.responder)
        response = self.client.get(reverse("escalations:queue"))
        self.assertContains(response, 'id="persistent-panel"')


class EscalationFactoryTests(TestCase):
    def test_escalation_factories_build_related_objects(self):
        escalation = make_escalation()
        assessment = make_assessment(escalation=escalation)
        event = make_escalation_event(escalation=escalation)

        self.assertEqual(assessment.escalation, escalation)
        self.assertEqual(event.escalation, escalation)
        self.assertEqual(
            assessment.assessed_by.user_role,
            User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
        )
