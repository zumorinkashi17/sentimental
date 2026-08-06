import json
import calendar
from datetime import datetime, timedelta, date
from django.shortcuts import render
from itertools import groupby
from django.http import JsonResponse, request
from django.views.decorators.http import require_POST
from .models import ShiftCatalog, ShiftSchedule
from apps.accounts.models import User, DayOffRequest

def admin_calendar_view(request):
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')
    
    responders = User.objects.filter(
        user_role=User.RoleChoices.RESPONDER,
        user_status=User.StatusChoices.ACTIVE 
    ).order_by('user_first_name')
    
    scheduled_roster = ShiftSchedule.objects.select_related('user', 'shift').order_by(
        'user__user_first_name', 'user__user_last_name', 'user_id', 'shift_date'
    )
    
    today = date.today()
    cal = calendar.Calendar(firstweekday=6)
    
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
            if user_schedules[0].schedule_status == 'Day Off':
                current_block['days_off'] = {user_schedules[0].shift_date.strftime("%A").lower()}

            for s in user_schedules[1:]:
                is_contiguous = (s.shift_date == current_block['shift_end_date'] + timedelta(days=1))
                is_same_shift = (s.shift == current_block['shift'])

                if is_contiguous and is_same_shift:
                    current_block['shift_end_date'] = s.shift_date
                    # Add the exact status for this specific date
                    current_block['daily_statuses'][s.shift_date.strftime("%Y-%m-%d")] = s.schedule_status
                else:
                    # Dump to JSON before appending
                    current_block['daily_statuses_json'] = json.dumps(current_block['daily_statuses'])
                    reconstructed_blocks.append(current_block)
                    
                    # Start new block
                    current_block = {
                        'shift': s.shift,
                        'shift_start_date': s.shift_date,
                        'shift_end_date': s.shift_date,
                        'daily_statuses': {
                            s.shift_date.strftime("%Y-%m-%d"): s.schedule_status
                        },
                        'schedule_id': s.schedule_id
                    }
                    
            # Append the final block
            current_block['daily_statuses_json'] = json.dumps(current_block['daily_statuses'])
            reconstructed_blocks.append(current_block)

        # Determine how far into the future we need to generate calendars for this user
        max_date = today
        if user_schedules:
            max_date = max(s.shift_date for s in user_schedules)

        curr_y, curr_m = today.year, today.month
        end_y, end_m = max_date.year, max_date.month

        months_to_generate = []
        months_count = 0
        
        # Generate from this month up to their last scheduled month (minimum 3 months total)
        while True:
            months_to_generate.append((curr_y, curr_m))
            months_count += 1
            
            # Stop if we've passed their max schedule date AND we've shown at least 3 months
            if (curr_y > end_y or (curr_y == end_y and curr_m >= end_m)) and months_count >= 3:
                break
                
            if curr_m == 12:
                curr_y += 1
                curr_m = 1
            else:
                curr_m += 1

        user_months = []
        
        schedule_dict = {s.shift_date: s for s in user_schedules}
        
        # Build the grid for every month in the generated range
        for y, m in months_to_generate:
            month_days = list(cal.itermonthdates(y, m))
            user_grid = []
            
            for d in month_days:
                day_data = {
                    'date': d,
                    'day_num': d.day,
                    'is_current_month': d.month == m,
                    'is_today': d == today,
                    'shift': None,
                    'is_day_off': False,
                    'is_leave': False,
                }
                
                # CHANGED: Direct dictionary lookup instead of looping through all dates
                if d in schedule_dict:
                    schedule = schedule_dict[d]
                    if schedule.schedule_status == 'Day Off':
                        day_data['is_day_off'] = True
                    elif schedule.schedule_status == 'Leave':
                        day_data['is_leave'] = True
                    else:
                        day_data['is_day_off'] = False
                        day_data['shift'] = schedule.shift
                        
                user_grid.append(day_data)
                
            user_months.append({
                'month_name': calendar.month_name[m],
                'year': y,
                'grid': user_grid
            })
            
        grouped_roster.append({
            'user': user,
            'schedules': reconstructed_blocks,
            'months': user_months  
        })

    pending_leaves = DayOffRequest.objects.filter(
        requested_status=DayOffRequest.StatusChoices.PENDING
    ).select_related('user').order_by('requested_date')

    approved_leaves = DayOffRequest.objects.filter(
        requested_status=DayOffRequest.StatusChoices.APPROVED,
        requested_date__gte=today
    ).order_by('requested_date')
    
    leaves_data = {}
    for leave in approved_leaves:
        uid = str(leave.user_id)
        if uid not in leaves_data:
            leaves_data[uid] = []
        leaves_data[uid].append(leave.requested_date.strftime('%A, %b %d, %Y'))

    context = {
        'shifts': shifts,
        'responders': responders,
        'grouped_roster': grouped_roster,
        'today_date': today,
        'leaves_data_json': json.dumps(leaves_data),
        'pending_leaves': pending_leaves,
    }
    return render(request, 'schedules/admin_calendar.html', context)

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

        # 1. Update the overlap check to use the new shift_date field
        has_overlap = ShiftSchedule.objects.filter(
            user=responder, 
            shift_date__range=[start_date, end_date]
        ).exists()

        if has_overlap:
            return JsonResponse({
                'status': 'error', 
                'message': 'This responder already has scheduled days within this date range.'
            }, status=400)

        # 2. Loop through the dates and prepare them for bulk creation
        schedules_to_create = []
        delta = timedelta(days=1)
        current_date = start_date

        while current_date <= end_date:
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

        # 3. Bulk insert all days at once for database efficiency
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
    calendar_grid = []
    
    today = date.today()
    try:
        current_year = int(request.GET.get('year', today.year))
        current_month = int(request.GET.get('month', today.month))
    except ValueError:
        current_year = today.year
        current_month = today.month

    # Basic validation to prevent weird URL manipulation
    if current_month < 1 or current_month > 12:
        current_month = today.month
        current_year = today.year

    current_month_name = calendar.month_name[current_month]

    # 2. Calculate Next and Previous months to pass to the buttons
    if current_month == 1:
        prev_month = 12
        prev_year = current_year - 1
    else:
        prev_month = current_month - 1
        prev_year = current_year
        
    if current_month == 12:
        next_month = 1
        next_year = current_year + 1
    else:
        next_month = current_month + 1
        next_year = current_year

    if current_user:
        dayoff_requests = DayOffRequest.objects.filter(user=current_user).order_by('-requested_date')
        
        # 1. Fetch ALL shifts (Removed the status filter so we get Days Off and Leaves too)
        my_schedules = ShiftSchedule.objects.filter(
            user=current_user
        ).select_related('shift')

        # 2. Create a dictionary for fast date lookups
        schedule_dict = {s.shift_date: s for s in my_schedules}

        # Build a visual calendar grid (starts on Sunday = 6)
        cal = calendar.Calendar(firstweekday=6)
        month_days = cal.itermonthdates(current_year, current_month)

        for d in month_days:
            day_data = {
                'date': d,
                'day_num': d.day,
                'is_current_month': d.month == current_month,
                'is_today': d == today,
                'shift': None,
                'is_day_off': False,
                'is_leave': False, # 3. Added Leave flag
            }
            
            # 4. Check the exact date in our dictionary instead of start/end ranges
            if d in schedule_dict:
                schedule = schedule_dict[d]
                if schedule.schedule_status == 'Day Off':
                    day_data['is_day_off'] = True
                elif schedule.schedule_status == 'Leave':
                    day_data['is_leave'] = True
                else:
                    day_data['shift'] = schedule.shift
                    
            calendar_grid.append(day_data)
    context = {
        'dayoff_requests': dayoff_requests,
        'calendar_grid': calendar_grid,
        'current_month_name': current_month_name,
        'current_year': current_year,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
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

        leave_request = DayOffRequest.objects.get(request_id=leave_id)
        if action == 'approve':
            leave_request.requested_status = DayOffRequest.StatusChoices.APPROVED
        elif action == 'deny':
            leave_request.requested_status = DayOffRequest.StatusChoices.DENIED
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid action received.'}, status=400)

        # Save to database
        leave_request.save()

        return JsonResponse({'status': 'success', 'message': f'Request {action}d successfully.'})

    except DayOffRequest.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Day off request not found.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)