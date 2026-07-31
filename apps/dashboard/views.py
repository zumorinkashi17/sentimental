from django.shortcuts import render, redirect
from apps.accounts.models import User
from apps.schedules.models import ShiftCatalog
from apps.callers.models import CallSession

def _get_session_user(request, required_role=None):
    """Return (user, None) or (None, redirect_response)."""
    user_id = request.session.get("user_id")
    print(f"DEBUG: Checking session. user_id = {user_id}") # <-- ADD THIS
    
    if not user_id:
        return None, redirect("accounts:login")

    try:
        user = User.objects.get(user_id=user_id)
    except User.DoesNotExist:
        print("DEBUG: User found in session, but not in DB!") # <-- ADD THIS
        request.session.flush()
        return None, redirect("accounts:login")

    print(f"DEBUG: User found. Status = {user.user_status}, Role = {user.user_role}") # <-- ADD THIS

    if user.user_status != User.StatusChoices.ACTIVE:
        print("DEBUG: User is NOT Active. Kicking out.") # <-- ADD THIS
        request.session.flush()
        return None, redirect("accounts:login")

    if required_role and user.user_role != required_role:
        print(f"DEBUG: Role mismatch! Required: {required_role}, Actual: {user.user_role}") # <-- ADD THIS
        if user.user_role == User.RoleChoices.ADMIN:
            return None, redirect("dashboard:admin_dashboard")
        elif user.user_role == User.RoleChoices.RESPONDER:
            return None, redirect("dashboard:responder_dashboard")
        else:
            request.session.flush()
            return None, redirect("accounts:login")

    print("DEBUG: User passed all checks. Allowing access.") # <-- ADD THIS
    return user, None


def _get_panel_data():
    """Helper function to get data needed for the persistent right panel."""
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')

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
    
    return {
        "shifts": shifts,
        "next_session_id": next_session_id
    }

# --- Main Dashboards ---

def admin_dashboard(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')

    prefix = 'TPCB10-'
    last_session = CallSession.objects.filter(
        session_id__startswith=prefix
    ).order_by('-session_id').first()
    
    if last_session:
        # Split 'TPCB10-0005' -> grab '0005', make it an int, add 1
        last_number = int(last_session.session_id.split('-')[1])
        new_number = last_number + 1
    else:
        new_number = 1
        
    # Format with leading zeros
    next_session_id = f"{prefix}{new_number:04d}"
    
    if redirect_response:
        return redirect_response
    return render(request, "dashboard/admin_dashboard.html", {"user": user, "shifts": shifts, "next_session_id": next_session_id})

def responder_dashboard(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.RESPONDER)
    shifts = ShiftCatalog.objects.all().order_by('shift_start_time')
    
    prefix = 'TPCB10-'
    last_session = CallSession.objects.filter(
        session_id__startswith=prefix
    ).order_by('-session_id').first()
    
    if last_session:
        # Split 'TPCB10-0005' -> grab '0005', make it an int, add 1
        last_number = int(last_session.session_id.split('-')[1])
        new_number = last_number + 1
    else:
        new_number = 1
        
    # Format with leading zeros
    next_session_id = f"{prefix}{new_number:04d}"
    
    if redirect_response:
        return redirect_response
    return render(request, "dashboard/responder_dashboard.html", {"user": user, "shifts": shifts, "next_session_id": next_session_id})

# --- Other Pages ---

def index(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
        
    context = {"user": user}
    context.update(_get_panel_data()) # <-- Add the panel data to context
    return render(request, "dashboard/index.html", context)

def dashboard_general(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
        
    context = {"user": user}
    context.update(_get_panel_data()) 
    return render(request, "dashboard/dashboard.html", context)

def admin_index(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
    if redirect_response:
        return redirect_response
        
    context = {"user": user}
    context.update(_get_panel_data()) 
    return render(request, "dashboard/admin_index.html", context)

def call_logs(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
        
    context = {"user": user}
    context.update(_get_panel_data()) # <-- Add the panel data to context
    return render(request, "dashboard/call_logs.html", context)

def call_logs_admin(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
    if redirect_response:
        return redirect_response
        
    context = {"user": user}
    context.update(_get_panel_data()) 
    return render(request, "dashboard/call_logs_admin.html", context)
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
    if redirect_response:
        return redirect_response
    return render(request, "dashboard/call_logs_admin.html", {"user": user})