import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import ShiftCatalog

def admin_calendar_view(request):
    # Fetch all shifts to display in the new catalog table
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')
    return render(request, 'schedules/admin_calendar.html', {'shifts': shifts})

@require_POST
def add_shift(request):
    try:
        data = json.loads(request.body)
        
        # Create the new shift in the database
        ShiftCatalog.objects.create(
            shift_name=data.get('shift_name'),
            shift_start_time=data.get('start_time'),
            shift_end_time=data.get('end_time')
        )
        
        return JsonResponse({'status': 'success', 'message': 'Shift added successfully.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)