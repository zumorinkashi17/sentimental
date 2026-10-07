import json
import calendar
from datetime import datetime, timedelta, date
from django.shortcuts import render
from itertools import groupby
from django.http import JsonResponse, request
from django.views.decorators.http import require_POST
from .models import ShiftCatalog, ShiftSchedule
from apps.accounts.models import User, DayOffRequest
from django.db import transaction

def admin_calendar_view(request):
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')
    
    responders = User.objects.filter(
        user_role=User.RoleChoices.RESPONDER,
        user_status=User.StatusChoices.ACTIVE 
    ).order_by('user_first_name')
    
    scheduled_roster = ShiftSchedule.objects.select_related('user', 'shift').order_by(
        'user__user_first_name', 'user__user_last_name', 'user_id', 'shift_date'
    )
    
    # --- STATS CALCULATIONS ---
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) # Monday
    end_of_week = start_of_week + timedelta(days=6) # Sunday
    
    active_today_count = ShiftSchedule.objects.filter(
        shift_date=today, 
        schedule_status='Scheduled'
    ).values('user').distinct().count()
    
    active_week_count = ShiftSchedule.objects.filter(
        shift_date__range=[start_of_week, end_of_week], 
        schedule_status='Scheduled'
    ).values('user').distinct().count()
    
    active_month_count = ShiftSchedule.objects.filter(
        shift_date__year=today.year, 
        shift_date__month=today.month, 
        schedule_status='Scheduled'
    ).values('user').distinct().count()
    
    # Separated Queries for Days Off and Leaves
    dayoff_week_count = ShiftSchedule.objects.filter(
        shift_date__range=[start_of_week, end_of_week], 
        schedule_status='Day Off'
    ).values('user').distinct().count()

    leave_week_count = ShiftSchedule.objects.filter(
        shift_date__range=[start_of_week, end_of_week], 
        schedule_status='Leave'
    ).values('user').distinct().count()
    # ------------------------------

    grouped_roster = []
    
    for user, user_schedules_iter in groupby(scheduled_roster, key=lambda s: s.user):
        user_schedules = list(user_schedules_iter)
        reconstructed_blocks = []
        
        if user_schedules:
            current_block = {
                'shift': user_schedules[0].shift,
                'shift_start_date': user_schedules[0].shift_date,
                'shift_end_date': user_schedules[0].shift_date,
                'daily_statuses': {
                    user_schedules[0].shift_date.strftime("%Y-%m-%d"): user_schedules[0].schedule_status
                },
                'schedule_id': user_schedules[0].schedule_id 
            }

            for s in user_schedules[1:]:
                is_contiguous = (s.shift_date == current_block['shift_end_date'] + timedelta(days=1))
                is_same_shift = (s.shift == current_block['shift'])

                if is_contiguous and is_same_shift:
                    current_block['shift_end_date'] = s.shift_date
                    current_block['daily_statuses'][s.shift_date.strftime("%Y-%m-%d")] = s.schedule_status
                else:
                    current_block['daily_statuses_json'] = json.dumps(current_block['daily_statuses'])
                    reconstructed_blocks.append(current_block)
                    
                    current_block = {
                        'shift': s.shift,
                        'shift_start_date': s.shift_date,
                        'shift_end_date': s.shift_date,
                        'daily_statuses': {
                            s.shift_date.strftime("%Y-%m-%d"): s.schedule_status
                        },
                        'schedule_id': s.schedule_id
                    }
                    
            current_block['daily_statuses_json'] = json.dumps(current_block['daily_statuses'])
            reconstructed_blocks.append(current_block)
            
        grouped_roster.append({
            'user': user,
            'schedules': reconstructed_blocks
        })

    pending_leaves = DayOffRequest.objects.filter(
        requested_status=DayOffRequest.StatusChoices.PENDING
    ).select_related('user').order_by('requested_date')

    processed_leaves = DayOffRequest.objects.exclude(
        requested_status=DayOffRequest.StatusChoices.PENDING
    ).select_related('user').order_by('-requested_date')[:25] 

    context = {
        'shifts': shifts,
        'responders': responders,
        'grouped_roster': grouped_roster,
        'today_date': today,
        'pending_leaves': pending_leaves,
        'processed_leaves': processed_leaves, 
        
        'active_today_count': active_today_count,
        'active_week_count': active_week_count,
        'active_month_count': active_month_count,
        'dayoff_week_count': dayoff_week_count,
        'leave_week_count': leave_week_count,
    }
    return render(request, 'schedules/admin_calendar.html', context)

def api_user_schedule(request, user_id):
    schedules = ShiftSchedule.objects.filter(user_id=user_id).select_related('shift')
    events = []
    
    for sched in schedules:
        events.append({
            "title": "Shift" if sched.schedule_status == 'Scheduled' else sched.schedule_status,
            "start": f"{sched.shift_date}T{sched.shift.shift_start_time}",
            "end": f"{sched.shift_date}T{sched.shift.shift_end_time}",
            "extendedProps": {
                "status": sched.schedule_status.lower()
            }
        })
        
    return JsonResponse(events, safe=False)

@require_POST
def update_schedule_days_off(request):
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        shift_id = data.get('shift_id')
        daily_updates = data.get('daily_updates', []) 

        responder = User.objects.get(user_id=user_id)
        shift = ShiftCatalog.objects.get(shift_id=shift_id)

        # Loop through the JS array and update each day individually
        for update in daily_updates:
            target_date = datetime.strptime(update['date'], "%Y-%m-%d").date()
            new_status = update['status']
            
            # Fetch the existing schedule record for this specific day
            ShiftSchedule.objects.filter(
                user=responder,
                shift_date=target_date,
                shift=shift
            ).update(schedule_status=new_status)

        return JsonResponse({'status': 'success', 'message': 'Calendar block updated successfully.'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@require_POST
def add_shift(request):
    
    try:
        data = json.loads(request.body)
        
        ShiftCatalog.objects.create(
            shift_start_time=data.get('start_time'),
            shift_end_time=data.get('end_time')
        )
        
        return JsonResponse({'status': 'success', 'message': 'Shift added successfully.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@require_POST
def save_schedule(request):
    try:
        data = json.loads(request.body)
        
        responder_id = data.get('responder_id')
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        shift_id = data.get('shift_id')
        day_offs = data.get('day_off', [])

        # Fetch instances
        responder = User.objects.get(user_id=responder_id)
        shift = ShiftCatalog.objects.get(shift_id=shift_id)
        
        # Convert strings to date objects
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

        if start_date > end_date:
            return JsonResponse({'status': 'error', 'message': 'Start date cannot be after end date.'}, status=400)

        # Fetch all existing schedules in this date range
        existing_schedules = ShiftSchedule.objects.filter(
            user=responder, 
            shift_date__range=[start_date, end_date]
        )

        # Check for ACTUAL conflicts. We exclude 'Leave' because we want to allow generating 
        # schedules around already-approved leaves.
        actual_conflicts = existing_schedules.exclude(schedule_status='Leave')

        if actual_conflicts.exists():
            return JsonResponse({
                'status': 'error', 
                'message': 'This responder already has scheduled shifts or days off within this date range.'
            }, status=400)

        # 3Get a fast lookup set of the dates that are already saved in the database (e.g., the Leave days)
        existing_dates = set(existing_schedules.values_list('shift_date', flat=True))

        schedules_to_create = []
        delta = timedelta(days=1)
        current_date = start_date

        # Loop through the dates and prepare them for bulk creation
        while current_date <= end_date:
            
            # IF THIS DATE ALREADY EXISTS IN THE DB (Like an approved leave), SKIP IT!
            if current_date in existing_dates:
                current_date += delta
                continue

            # Get the string name of the day (e.g., 'monday', 'tuesday')
            day_name = current_date.strftime("%A").lower()
            
            # Determine the status for this specific date
            if day_name in day_offs:
                status = 'Day Off'
            else:
                status = 'Scheduled'
            
            # Append the instance to our list (not hitting the DB yet)
            schedules_to_create.append(
                ShiftSchedule(
                    user=responder,
                    shift=shift,
                    shift_date=current_date,
                    schedule_status=status
                )
            )
            
            # Move to the next day
            current_date += delta

        # 5. Bulk insert all new days at once for database efficiency
        ShiftSchedule.objects.bulk_create(schedules_to_create)
        
        return JsonResponse({'status': 'success', 'message': 'Shift schedule generated successfully!'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def responder_schedule_view(request):
    # Determine current user
    if hasattr(request, 'user') and request.user.is_authenticated:
        current_user = request.user
    else:
        current_user = None
        user_id = request.session.get('user_id')
        if user_id:
            try:
                current_user = User.objects.get(user_id=user_id)
            except User.DoesNotExist:
                current_user = None

    dayoff_requests = DayOffRequest.objects.none()
    events = []

    if current_user:
        dayoff_requests = DayOffRequest.objects.filter(user=current_user).order_by('-requested_date')
        
        my_schedules = ShiftSchedule.objects.filter(
            user=current_user
        ).select_related('shift')

        for sched in my_schedules:
            status = sched.schedule_status
            
            if status == 'Scheduled' and sched.shift:
                time_str = f"{sched.shift.shift_start_time.strftime('%I:%M %p')} - {sched.shift.shift_end_time.strftime('%I:%M %p')}"
                events.append({
                    "id": sched.schedule_id,
                    "title": f"Shift ({time_str})",
                    "start": f"{sched.shift_date}T{sched.shift.shift_start_time.strftime('%H:%M:%S')}",
                    "end": f"{sched.shift_date}T{sched.shift.shift_end_time.strftime('%H:%M:%S')}",
                    "allDay": False,
                    "backgroundColor": "#00a67e",
                    "borderColor": "#007a5d",
                    "textColor": "#ffffff",
                    "extendedProps": {
                        "status": "Scheduled",
                        "time": time_str
                    }
                })
            elif status == 'Day Off':
                events.append({
                    "id": sched.schedule_id,
                    "title": "Day Off",
                    "start": str(sched.shift_date),
                    "allDay": True,
                    "backgroundColor": "#3b82f6",
                    "borderColor": "#2563eb",
                    "textColor": "#ffffff",
                    "extendedProps": {
                        "status": "Day Off"
                    }
                })
            elif status == 'Leave':
                events.append({
                    "id": sched.schedule_id,
                    "title": "Leave",
                    "start": str(sched.shift_date),
                    "allDay": True,
                    "backgroundColor": "#f97316",
                    "borderColor": "#ea580c",
                    "textColor": "#ffffff",
                    "extendedProps": {
                        "status": "Leave"
                    }
                })

    context = {
        'dayoff_requests': dayoff_requests,
        'events_json': json.dumps(events),
    }
    
    return render(request, 'schedules/calendar.html', context)

@require_POST
def submit_dayoff_request(request):
    try:
        data = json.loads(request.body)
        
        if hasattr(request, 'user') and request.user.is_authenticated:
            current_user = request.user
        else:
            current_user = None
            user_id = request.session.get('user_id')
            if user_id:
                try:
                    current_user = User.objects.get(user_id=user_id)
                except User.DoesNotExist:
                    current_user = None

        if not current_user:
            return JsonResponse({'status': 'error', 'message': 'User not authenticated.'}, status=401)

        DayOffRequest.objects.create(
            user=current_user,
            requested_date=data.get('date'),
            requested_reason=data.get('reason'),
            requested_additional_notes=data.get('notes', ''),
            requested_status=DayOffRequest.StatusChoices.PENDING
        )
        
        return JsonResponse({'status': 'success', 'message': 'Request submitted successfully.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    
@require_POST
def update_dayoff_status(request):
    try:
        data = json.loads(request.body)
        leave_id = data.get('leave_id')
        action = data.get('action')

        with transaction.atomic():
            leave_request = DayOffRequest.objects.select_for_update().get(request_id=leave_id)
            
            if action == 'approve':
                leave_request.requested_status = DayOffRequest.StatusChoices.APPROVED
                
                # ... (Keep your existing existing_schedules checking code here) ...
                
            elif action == 'deny':
                leave_request.requested_status = DayOffRequest.StatusChoices.DENIED
                
            # NEW: Handle the cancellation from the responder
            elif action == 'cancel':
                # Ensure they can only cancel it if it hasn't been approved/denied yet
                if leave_request.requested_status == DayOffRequest.StatusChoices.PENDING:
                    # Update this exact string to match whatever 'Cancel' choice is in your models.py
                    leave_request.requested_status = 'Canceled' 
                else:
                    return JsonResponse({'status': 'error', 'message': 'Only pending requests can be canceled.'}, status=400)
                    
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid action received.'}, status=400)

            # Save the DayOffRequest status to the database
            leave_request.save()

        return JsonResponse({'status': 'success', 'message': f'Request {action}d successfully.'})

    except DayOffRequest.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Day off request not found.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)