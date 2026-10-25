import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from apps.accounts.models import User
from django.db.models import CharField, Count, OuterRef, Q, Subquery
from django.db.models.functions import Cast
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from apps.pagination import paginate
from .models import Caller, CallSession, CallTranscript
from apps.schedules.models import ShiftCatalog
from apps.dashboard.views import _get_session_user
from .audio import AudioProcessingError
from .nlp import analyze
from .transcription import (
    CALLER,
    RESPONDER,
    TranscriptionError,
    normalize_track,
    transcribe_tracks,
)

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
@ensure_csrf_cookie
def call_setup_view(request):
    """Displays the call setup page and ensures the CSRF cookie is set."""
    _, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    return render(request, 'components/call_setup.html')

# Gets a field from the caller's latest session.
def _latest_session_subquery():
    return (
        CallSession.objects
        .filter(caller=OuterRef('pk'))
        .order_by('-session_call_date', '-session_time_called')
        .values('pk')[:1]
    )

# Correlated subquery selecting ``field`` from a caller's latest session.
def _latest_session_value(field):
    return (
        CallSession.objects
        .filter(caller=OuterRef('pk'))
        .order_by('-session_call_date', '-session_time_called')
        .values(field)[:1]
    )

# Builds the base caller queryset with required annotations
def _annotated_callers(include_totals=False):
    callers = Caller.objects.annotate(
        caller_id_text=Cast('caller_id', output_field=CharField()),
        latest_session_id=Subquery(_latest_session_subquery()),
        latest_session_date=Subquery(_latest_session_value('session_call_date')),
        latest_session_risk=Subquery(_latest_session_value('session_risk_assessment')),
    )
    if include_totals:
        callers = callers.annotate(total_sessions=Count('callsession'))
    return callers

# Applies search, risk, and time filters on the server.
def _apply_caller_filters(callers, request):
    search = (request.GET.get('search') or '').strip()
    risk = (request.GET.get('risk') or 'all').lower()
    period = (request.GET.get('period') or 'all').lower()

    if search:
        filters = Q(caller_name__icontains=search)
        if search.isdigit():
            filters |= Q(caller_id_text__icontains=search)
        callers = callers.filter(filters)

    if risk in ('high', 'medium', 'low'):
        callers = callers.filter(latest_session_risk__icontains=risk)

    today = timezone.localdate()
    if period == 'today':
        callers = callers.filter(latest_session_date=today)
    elif period == 'week':
        js_weekday = (today.weekday() + 1) % 7
        callers = callers.filter(latest_session_date__gte=today - timedelta(days=js_weekday))
    elif period == 'month':
        callers = callers.filter(latest_session_date__gte=today.replace(day=1))

    return callers


def _build_caller_list(callers, include_totals=False):
    """Builds template rows using one query to fetch the latest sessions."""
    session_ids = [caller.latest_session_id for caller in callers if caller.latest_session_id]
    sessions_by_id = CallSession.objects.select_related('user').in_bulk(session_ids)

    caller_list = []
    for caller in callers:
        row = {
            'caller': caller,
            'latest_session': sessions_by_id.get(caller.latest_session_id),
        }
        if include_totals:
            row['total_sessions'] = caller.total_sessions
        caller_list.append(row)
    return caller_list


def list_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    callers = _apply_caller_filters(_annotated_callers(), request).order_by('-caller_id')
    page_obj, querystring = paginate(request, callers)
    caller_list = _build_caller_list(page_obj.object_list)

    return render(request, 'callers/list.html', {
        'caller_list': caller_list,
        'page_obj': page_obj,
        'querystring': querystring,
    })

def database_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    callers = _apply_caller_filters(_annotated_callers(include_totals=True), request).order_by('-caller_id')
    page_obj, querystring = paginate(request, callers)
    caller_list = _build_caller_list(page_obj.object_list, include_totals=True)

    return render(request, 'callers/database.html', {
        'caller_list': caller_list,
        'page_obj': page_obj,
        'querystring': querystring,
    })

# Keeps the codec hint simple, such as 'opus'.
def _clean_codec(value):
    if not value:
        return None
    cleaned = "".join(ch for ch in str(value).lower() if ch.isalnum())
    return cleaned or None


# Handles the transcription POST request, normalizes both tracks, transcribes them, and returns the results as JSON.
@require_POST
def transcribe_audio(request):
    """
    Transcribes the caller and responder audio separately.

    Expects caller and responder audio files.
    Normalizes each track, transcribes them, and merges the segments by start time.
    """
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    caller_upload = request.FILES.get("caller")
    responder_upload = request.FILES.get("responder")

    if not caller_upload or not responder_upload:
        missing = []
        if not caller_upload:
            missing.append("caller")
        if not responder_upload:
            missing.append("responder")
        return JsonResponse(
            {
                "status": "error",
                "message": f"Missing audio track(s): {', '.join(missing)}. "
                           "Record a call with both inputs enabled before transcribing.",
            },
            status=400,
        )

    api_key = (settings.GEMINI_API_KEY or "").strip()
    if not api_key:
        return JsonResponse(
            {
                "status": "error",
                "message": "Gemini API key is not configured. Add GEMINI_API_KEY=AIza... "
                           "to your .env file and restart the server.",
            },
            status=500,
        )

    try:
        # Normalizes both tracks at the same time to reduce processing time by using pydub to decodes each one.
        with ThreadPoolExecutor(max_workers=2) as pool:
            caller_future = pool.submit(
                normalize_track,
                caller_upload,
                CALLER,
                codec=_clean_codec(request.POST.get("caller_codec")),
            )
            responder_future = pool.submit(
                normalize_track,
                responder_upload,
                RESPONDER,
                codec=_clean_codec(request.POST.get("responder_codec")),
            )
            caller_track = caller_future.result()
            responder_track = responder_future.result()
    except AudioProcessingError as exc:
        logger.warning("Track normalization failed: %s", exc)
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

    try:
        segments, transcript = transcribe_tracks(
            caller_track.wav, responder_track.wav, api_key
        )
    except TranscriptionError as exc:
        logger.warning("Transcription failed: %s", exc)
        return JsonResponse({"status": "error", "message": str(exc)}, status=502)

    return JsonResponse(
        {
            "status": "success",
            "transcript": transcript,
            "segments": segments,
            "durations": {CALLER: caller_track.duration_ms, RESPONDER: responder_track.duration_ms},
            # Shows the responder the audio levels of both tracks.
            "levels": {CALLER: caller_track.as_levels(), RESPONDER: responder_track.as_levels()},
        }
    )


@require_POST
def analyze_call_text(request):
    """Run the hybrid NLP pipeline over a transcript / manual notes."""
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    try:
        data = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    text = str(data.get("text") or "").strip()
    if not text:
        return JsonResponse(
            {"status": "error", "message": "No transcript or manual notes to analyze."},
            status=400,
        )
    if len(text) > 50000:
        return JsonResponse(
            {"status": "error", "message": "Text is too long to analyze."},
            status=400,
        )

    try:
        result = analyze(
            text,
            reason_for_calling=data.get("reason", ""),
            risk_assessment=data.get("risk", ""),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("NLP analysis failed")
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)

    return JsonResponse(result)


@require_POST
def save_call_documentation(request):
    try:
        data = json.loads(request.body)

        user_id = request.session.get("user_id")
        current_user = None
        if user_id:
            current_user = User.objects.filter(user_id=user_id).first()

        try:
            call_date = datetime.strptime(data.get('callDate', ''), '%B %d, %Y').date()
        except ValueError:
            call_date = None
            
        # Format: "06:12 PM"
        def parse_time(time_str):
            try:
                return datetime.strptime(time_str, '%I:%M %p').time()
            except ValueError:
                return None
                
        time_called = parse_time(data.get('timeCalled', ''))
        time_ended = parse_time(data.get('timeEnded', ''))
        
        # Safely convert age
        age_str = data.get('callerAge')
        caller_age = int(age_str) if age_str and age_str.isdigit() else None

        # Fetch the Shift Instance from the database
        shift_id = data.get('callShift')
        shift_instance = None
        
        if shift_id:
            # Look up the shift using its primary key (ID) instead of its name
            shift_instance = ShiftCatalog.objects.filter(pk=shift_id).first()

        # Create the Caller record
        caller = Caller.objects.create(
            caller_name=data.get('callerName'),
            caller_gender=data.get('callerGender'),
            caller_civil_status=data.get('callerStatus'),
            caller_age=caller_age,
            caller_location=data.get('callerLocation')
        )

        # Create the Call Session record
        session = CallSession.objects.create(
            user=current_user,
            caller=caller,
            shift=shift_instance,
            session_call_date=call_date,
            session_time_called=time_called,
            session_time_ended=time_ended,
            session_reason_for_calling=data.get('reasonForCalling'),
            session_risk_assessment=data.get('riskAssessment'),
            session_intervention=data.get('intervention'),
            session_summarization=data.get('aiSummary'),
            session_additional_comments=data.get('additionalComments')
        )

        # Persist the source text used for auto-fill, then any manual notes.
        raw_transcript = data.get('rawTranscript')
        if raw_transcript and raw_transcript.strip():
            CallTranscript.objects.create(
                session=session,
                transcript_text=raw_transcript
            )

        manual_notes = data.get('manualScriptNotes')
        if manual_notes and manual_notes.strip():
            CallTranscript.objects.create(
                session=session,
                transcript_text=manual_notes
            )

        return JsonResponse({
            'status': 'success', 
            'message': 'Session saved to Supabase',
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)