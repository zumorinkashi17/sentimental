from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.accounts.models import DayOffRequest, User


def get_notifications(request):
    role = request.session.get('user_role')

    if role == 'Admin':
        pending = DayOffRequest.objects.filter(
            requested_status=DayOffRequest.StatusChoices.PENDING
        ).select_related('user').order_by('requested_date')

        data = [
            {
                'id': r.request_id,
                'name': f"{r.user.user_first_name} {r.user.user_last_name}",
                'date': r.requested_date.strftime('%b %d, %Y'),
                'reason': r.requested_reason,
            }
            for r in pending
        ]

    elif role == 'Responder':
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'notifications': []})

        processed = DayOffRequest.objects.filter(
            user_id=user_id,
            is_read=False,
        ).exclude(
            requested_status=DayOffRequest.StatusChoices.PENDING
        ).order_by('-requested_date')

        data = [
            {
                'id': r.request_id,
                'status': r.requested_status,
                'date': r.requested_date.strftime('%b %d, %Y'),
                'reason': r.requested_reason,
            }
            for r in processed
        ]

    else:
        data = []

    return JsonResponse({'notifications': data})


@require_POST
def mark_read(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'status': 'error'}, status=401)

    DayOffRequest.objects.filter(
        user_id=user_id,
        is_read=False,
    ).exclude(
        requested_status=DayOffRequest.StatusChoices.PENDING
    ).update(is_read=True)

    return JsonResponse({'status': 'success'})
