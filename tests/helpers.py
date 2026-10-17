"""Shared fixtures for the test suite.

Small factory helpers keep the tests readable and insulated from the exact
field set of each model.
"""

from datetime import date, time

from apps.accounts.models import DayOffRequest, User
from apps.callers.models import Caller, CallSession
from apps.reports.models import Report
from apps.referrals.models import Institution, Professional
from apps.schedules.models import ShiftCatalog, ShiftSchedule


def make_user(
    email="user@example.com",
    role=User.RoleChoices.RESPONDER,
    status=User.StatusChoices.ACTIVE,
    first="Test",
    last="User",
    **kwargs,
):
    return User.objects.create(
        user_first_name=first,
        user_last_name=last,
        user_email=email,
        user_role=role,
        user_status=status,
        **kwargs,
    )


def make_shift(start=time(8, 0), end=time(17, 0)):
    return ShiftCatalog.objects.create(shift_start_time=start, shift_end_time=end)


def make_caller(name="Anonymous", gender=None, age=None, location=None, civil_status=None):
    return Caller.objects.create(
        caller_name=name,
        caller_gender=gender,
        caller_age=age,
        caller_location=location,
        caller_civil_status=civil_status,
    )


def make_session(
    user=None,
    caller=None,
    shift=None,
    on=None,
    at=time(9, 0),
    ended=None,
    risk=CallSession.RiskChoices.LOW,
    reason=None,
    summary="Call summary",
):
    """Create a CallSession. ``session_id`` is left to the model's allocator."""
    return CallSession.objects.create(
        user=user,
        caller=caller or make_caller(),
        shift=shift or make_shift(),
        session_call_date=on or date(2026, 1, 1),
        session_time_called=at,
        session_time_ended=ended,
        session_risk_assessment=risk,
        session_reason_for_calling=reason,
        session_summarization=summary,
    )


def make_institution(name="General Hospital", location="Cebu", status="Active"):
    return Institution.objects.create(
        institution_name=name,
        institution_location=location,
        institution_status=status,
    )


def make_professional(
    institution=None,
    name="Dr. Reyes",
    specialization="Psychiatry",
    status="Active",
    gender="Female",
):
    from django.utils import timezone

    return Professional.objects.create(
        institution=institution or make_institution(),
        professional_name=name,
        professional_specialization=specialization,
        professional_status=status,
        professional_gender=gender,
        professional_last_updated=timezone.now(),
    )


def make_day_off(user, status=DayOffRequest.StatusChoices.PENDING, is_read=False, on=None, reason="Vacation"):
    return DayOffRequest.objects.create(
        user=user,
        requested_date=on or date(2026, 2, 1),
        requested_reason=reason,
        requested_status=status,
        is_read=is_read,
    )


def make_report(user, title="Monthly Report", report_type="Analytics", generated=None):
    return Report.objects.create(
        report_title=title,
        report_generated_date=generated or date(2026, 1, 15),
        report_type=report_type,
        generated_by=user,
    )


def make_shift_schedule(user, shift=None, on=None, status="Scheduled"):
    return ShiftSchedule.objects.create(
        user=user,
        shift=shift or make_shift(),
        shift_date=on or date(2026, 1, 1),
        schedule_status=status,
    )


def login(client, user):
    """Populate the client session the way the app's session-based auth expects."""
    session = client.session
    session["user_id"] = user.user_id
    session["user_role"] = user.user_role
    session["user_name"] = f"{user.user_first_name} {user.user_last_name}"
    session.save()
    return client
