import json
from datetime import datetime
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.accounts.models import User
from django.shortcuts import render
from .models import Caller, CallSession, CallTranscript
from apps.schedules.models import ShiftCatalog
from apps.dashboard.views import _get_session_user

def list_view(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
    # Fetch all callers with no user restriction
    callers = Caller.objects.all().order_by('-caller_id')
    
    caller_list = []
    for caller in callers:
        # Get the most recent session for this specific caller
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

    # Fetch all callers
    callers = Caller.objects.all().order_by('-caller_id')
    
    caller_list = []
    for caller in callers:
        # Get the most recent session for this specific caller
        latest_session = CallSession.objects.filter(caller=caller).order_by('-session_call_date', '-session_time_called').first()
        
        # Count total sessions for the modal
        total_sessions = CallSession.objects.filter(caller=caller).count()
        
        caller_list.append({
            'caller': caller,
            'latest_session': latest_session,
            'total_sessions': total_sessions
        })

    return render(request, 'callers/database.html', {'caller_list': caller_list})


@require_POST
def save_call_documentation(request):
    try:
        data = json.loads(request.body)

        user_id = request.session.get("user_id")
        current_user = None
        if user_id:
            current_user = User.objects.filter(user_id=user_id).first()
        
        # 1. Parse Data Formats safely
        # Format: "October 04, 2024" -> Python date object
        try:
            call_date = datetime.strptime(data.get('callDate', ''), '%B %d, %Y').date()
        except ValueError:
            call_date = None
            
        # Format: "06:12 PM" -> Python time object
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

        # 2. Fetch the Shift Instance from the database
        shift_id = data.get('callShift')
        shift_instance = None
        
        if shift_id:
            # Look up the shift using its primary key (ID) instead of its name
            shift_instance = ShiftCatalog.objects.filter(pk=shift_id).first()

        # 2. Create the Caller record
        caller = Caller.objects.create(
            caller_name=data.get('callerName'),
            caller_gender=data.get('callerGender'),
            caller_civil_status=data.get('callerStatus'),
            caller_age=caller_age,
            caller_location=data.get('callerLocation')
        )

        # 3. Create the Call Session record
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

        # 4. Create the manual transcript if notes exist
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