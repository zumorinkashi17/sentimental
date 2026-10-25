from django.utils import timezone

from apps.schedules.models import ShiftSchedule

from .models import CallSession


def call_metadata(request):
    """Expose the next session number and today's shift to the persistent panel."""
    user = getattr(request, '_sentimental_user', None)
    if user is None:
        return {}

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

    return {
        'next_session_id': CallSession.next_session_preview(),
        'today_shift': schedule.shift if schedule else None,
    }
