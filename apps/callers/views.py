import json
import logging
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from apps.accounts.models import User
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from .models import Caller, CallSession, CallTranscript
from apps.schedules.models import ShiftCatalog
from apps.dashboard.views import _get_session_user
from .audio import AudioProcessingError
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
    """
    Serve the call setup page.

    ``ensure_csrf_cookie`` guarantees the csrftoken cookie exists, because the
    page posts the separated tracks to the transcribe endpoint and this page
    itself renders no ``{% csrf_token %}``.
    """
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')
    
    from datetime import date
    next_session_id = f"TPCB10-{Caller.objects.count() + 1:04d}"

    return render(request, 'components/call_setup.html', {
        'shifts': shifts,
        'next_session_id': next_session_id,
    })

def list_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    callers = Caller.objects.all().order_by('-caller_id')
    
    caller_list = []
    for caller in callers:
        latest_session = CallSession.objects.filter(caller=caller).order_by('-session_call_date', '-session_time_called').first()
        
        caller_list.append({
            'caller': caller,
            'latest_session': latest_session
        })

    return render(request, 'callers/list.html', {'caller_list': caller_list})

def database_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
    
    callers = Caller.objects.all().order_by('-caller_id')
    
    caller_list = []
    for caller in callers:

        latest_session = CallSession.objects.filter(caller=caller).order_by('-session_call_date', '-session_time_called').first()
        
        # Count total sessions for the modal
        total_sessions = CallSession.objects.filter(caller=caller).count()
        
        caller_list.append({
            'caller': caller,
            'latest_session': latest_session,
            'total_sessions': total_sessions
        })

    return render(request, 'callers/database.html', {'caller_list': caller_list})


def _clean_codec(value):
    """Keep the codec hint to a plain token; the browser sends e.g. 'opus'."""
    if not value:
        return None
    cleaned = "".join(ch for ch in str(value).lower() if ch.isalnum())
    return cleaned or None


@require_POST
def transcribe_audio(request):
    """
    Transcribe the isolated caller and responder tracks separately.

    Expects multipart/form-data with a `caller` and a `responder` audio file.
    Each track is normalized with pydub, transcribed on its own, and the two
    segment lists are merged by start time into a single conversation.
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
        caller_track = normalize_track(
            caller_upload, CALLER, codec=_clean_codec(request.POST.get("caller_codec"))
        )
        responder_track = normalize_track(
            responder_upload, RESPONDER, codec=_clean_codec(request.POST.get("responder_codec"))
        )
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
            # Reported back so the responder can see how each side was leveled.
            "levels": {CALLER: caller_track.as_levels(), RESPONDER: responder_track.as_levels()},
        }
    )


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

        # Create the manual transcript if notes exist
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