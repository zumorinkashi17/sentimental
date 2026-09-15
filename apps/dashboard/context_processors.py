from apps.schedules.models import ShiftCatalog
from apps.callers.models import CallSession

def persistent_panel_data(request):
    if not request.session.get('user_id'):
        return {}

    # Fetch Shifts
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')

    # Calculate next Session ID
    prefix = 'TPCB10-'
    last_session = CallSession.objects.filter(
        session_id__startswith=prefix
    ).order_by('-session_id').first()
    
    if last_session:
        last_number = int(last_session.session_id.split('-')[1])
        new_number = last_number + 1
    else:
        new_number = 1
        
    next_session_id = f"{prefix}{new_number:04d}"

    # Return the dictionary.
    return {
        'shifts': shifts,
        'next_session_id': next_session_id
    }