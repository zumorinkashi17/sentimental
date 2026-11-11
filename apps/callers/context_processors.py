from django.utils import timezone

from apps.accounts.models import User
from apps.schedules.models import ShiftCatalog, ShiftSchedule

from .models import CallSession


def _latest_shift_today():
    """Latest shift scheduled today, falling back to the latest shift catalog entry."""
    schedule = (
        ShiftSchedule.objects
        .filter(
            shift_date=timezone.localdate(),
            schedule_status='Scheduled',
        )
        .select_related('shift')
        .order_by('-shift__shift_start_time')
        .first()
    )
    if schedule and schedule.shift:
        return schedule.shift
    return ShiftCatalog.objects.order_by('-shift_start_time').first()


def call_metadata(request):
    """Expose the next session number and today's shift to the persistent panel."""
    user = getattr(request, '_sentimental_user', None)
    if user is None:
        return {}

    if user.user_role == User.RoleChoices.ADMIN:
        # Admins may not have a personal schedule, so use the latest shift today.
        today_shift = _latest_shift_today()
    else:
        schedule = (
            ShiftSchedule.objects
            .filter(
                user=user,
                shift_date=timezone.localdate(),
                schedule_status='Scheduled',
            )
            .select_related('shift')
            .first()
        )
        today_shift = schedule.shift if schedule else None

    return {
        'next_session_id': CallSession.next_session_preview(),
        'today_shift': today_shift,
    }
