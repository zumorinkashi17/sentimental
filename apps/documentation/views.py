from django.shortcuts import render
from apps.accounts.models import User
from django.utils import timezone
from apps.callers.models import CallSession
from apps.pagination import DEFAULT_PAGE_SIZE, paginate

from apps.dashboard.views import _get_session_user

def history_list_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
    sessions = CallSession.objects.select_related('user', 'caller')

    responder_filter = request.GET.get('responder', '')
    date_filter = request.GET.get('date_filter', '')
    highlight = request.GET.get('highlight', '')

    if responder_filter:
        sessions = sessions.filter(user_id=responder_filter)

    if date_filter:
        now = timezone.now()
        if date_filter == 'this_month':
            sessions = sessions.filter(
                session_call_date__year=now.year,
                session_call_date__month=now.month
            )
        elif date_filter == 'last_month':
            if now.month == 1:
                last_month = 12
                year = now.year - 1
            else:
                last_month = now.month - 1
                year = now.year
                
            sessions = sessions.filter(
                session_call_date__year=year,
                session_call_date__month=last_month
            )

    sessions = sessions.order_by('-session_call_date', '-session_time_called')

    responder_ids = CallSession.objects.values_list('user_id', flat=True).distinct()
    responders = User.objects.filter(user_id__in=responder_ids)

    # When a highlighted session is requested, jump to the page that contains it
    # so pagination does not hide the row the link pointed at.
    page_number = None
    if highlight and not request.GET.get('page'):
        session_ids = list(sessions.values_list('session_id', flat=True))
        try:
            index = session_ids.index(str(highlight))
            page_number = index // DEFAULT_PAGE_SIZE + 1
        except (ValueError, TypeError):
            page_number = None

    page_obj, querystring = paginate(request, sessions, page_number=page_number)

    context = {
        'sessions': page_obj.object_list,
        'page_obj': page_obj,
        'querystring': querystring,
        'responders': responders,
        'current_responder': responder_filter,
        'current_date_filter': date_filter,
        'highlight': highlight,
    }
    return render(request, 'documentation/master_history.html', context)


def user_history_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    current_user_id = request.session.get('user_id')
    
    sessions = (
        CallSession.objects
        .filter(user_id=current_user_id)
        .select_related('user', 'caller')
    )

    date_filter = request.GET.get('date_filter', '')

    if date_filter:
        now = timezone.now()
        if date_filter == 'this_month':
            sessions = sessions.filter(
                session_call_date__year=now.year,
                session_call_date__month=now.month
            )
        elif date_filter == 'last_month':
            if now.month == 1:
                last_month = 12
                year = now.year - 1
            else:
                last_month = now.month - 1
                year = now.year
                
            sessions = sessions.filter(
                session_call_date__year=year,
                session_call_date__month=last_month
            )

    sessions = sessions.order_by('-session_call_date', '-session_time_called')

    page_obj, querystring = paginate(request, sessions)

    context = {
        'sessions': page_obj.object_list,
        'page_obj': page_obj,
        'querystring': querystring,
        'current_date_filter': date_filter,
    }
    return render(request, 'documentation/history.html', context)