from django.shortcuts import render
from apps.accounts.models import User
from django.utils import timezone
from apps.callers.models import CallSession, CallTranscript
from apps.pagination import DEFAULT_PAGE_SIZE, paginate
from apps.referrals.models import SessionReferral

from apps.dashboard.views import _get_session_user
from apps.heatmap.views import (
    REGIONS,
    build_location_lookup,
    location_metadata,
    region_for_city,
    resolve_location,
)


def _attach_transcripts(sessions):
    """Attach each session's CallTranscript texts and return a lookup map."""
    sessions = list(sessions)
    session_ids = [session.session_id for session in sessions]
    transcript_map = {}

    if session_ids:
        rows = (
            CallTranscript.objects
            .filter(session_id__in=session_ids)
            .order_by('transcript_id')
        )
        for transcript in rows:
            transcript_map.setdefault(transcript.session_id, []).append(
                transcript.transcript_text or ''
            )

    for session in sessions:
        session.transcript_texts = transcript_map.get(session.session_id, [])

    return transcript_map


def _attach_referrals(sessions):
    """Attach each session's SessionReferral details and return a lookup map."""
    sessions = list(sessions)
    session_ids = [session.session_id for session in sessions]
    referral_map = {}

    if session_ids:
        referrals = (
            SessionReferral.objects
            .filter(session_id__in=session_ids)
            .select_related(
                'professional',
                'professional__institution',
                'affiliation__institution',
            )
            .prefetch_related('professional__professionalcontact_set')
        )
        for referral in referrals:
            professional = referral.professional
            affiliation = referral.affiliation
            institution = (
                (affiliation.institution if affiliation else None)
                or (professional.institution if professional else None)
            )
            contacts = (
                list(professional.professionalcontact_set.all())
                if professional else []
            )
            email = next(
                (c.contact_number for c in contacts if c.contact_type == 'Email'),
                '',
            )
            phone = next(
                (
                    c.contact_number for c in contacts
                    if c.contact_type in ('Mobile', 'Landline')
                ),
                '',
            )
            referral_map[referral.session_id] = {
                'institution': institution.institution_name if institution else '',
                'location': (
                    (institution.institution_location or '').strip()
                    if institution else ''
                ),
                'professional': (
                    professional.professional_name if professional else ''
                ),
                'specialization': (
                    professional.professional_specialization if professional else ''
                ),
                'contact': email or phone,
            }

    for session in sessions:
        session.referral = referral_map.get(session.session_id)

    return referral_map

def history_list_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
    sessions = CallSession.objects.select_related('user', 'caller')

    responder_filter = request.GET.get('responder', '')
    date_filter = request.GET.get('date_filter', '')
    region_filter = request.GET.get('region', '')
    location_filter = request.GET.get('location', '')
    highlight = request.GET.get('highlight', '')
    search_query = (request.GET.get('q') or request.GET.get('search') or '').strip()

    if search_query:
        sessions = sessions.filter(session_id__icontains=search_query)

    if responder_filter:
        sessions = sessions.filter(user_id=responder_filter)

    if location_filter or region_filter:
        # Match raw locations too, so "IT Park" counts under Cebu City.
        lookup = build_location_lookup()
        city_metadata = location_metadata()
        raw_locations = (
            CallSession.objects.values_list('caller__caller_location', flat=True).distinct()
        )
        if location_filter:
            target_city = resolve_location(location_filter, lookup)
            if target_city:
                matching = [
                    loc for loc in raw_locations
                    if loc and resolve_location(loc, lookup) == target_city
                ]
            else:
                matching = [location_filter]
        else:
            matching = [
                loc for loc in raw_locations
                if loc and region_for_city(resolve_location(loc, lookup), city_metadata) == region_filter
            ]
        sessions = sessions.filter(caller__caller_location__in=matching)

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
    page_sessions = list(page_obj.object_list)
    transcripts = _attach_transcripts(page_sessions)
    referrals = _attach_referrals(page_sessions)

    context = {
        'sessions': page_sessions,
        'page_obj': page_obj,
        'querystring': querystring,
        'responders': responders,
        'current_responder': responder_filter,
        'current_date_filter': date_filter,
        'current_region': region_filter,
        'current_region_label': dict(REGIONS).get(region_filter, '') if region_filter else '',
        'current_location': location_filter,
        'highlight': highlight,
        'search_query': search_query,
        'transcripts': transcripts,
        'referrals': referrals,
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
    search_query = (request.GET.get('q') or request.GET.get('search') or '').strip()

    if search_query:
        sessions = sessions.filter(session_id__icontains=search_query)

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
    page_sessions = list(page_obj.object_list)
    transcripts = _attach_transcripts(page_sessions)
    referrals = _attach_referrals(page_sessions)

    context = {
        'sessions': page_sessions,
        'page_obj': page_obj,
        'querystring': querystring,
        'current_date_filter': date_filter,
        'search_query': search_query,
        'transcripts': transcripts,
        'referrals': referrals,
    }
    return render(request, 'documentation/history.html', context)