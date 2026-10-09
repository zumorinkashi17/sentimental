from django.shortcuts import render, redirect
from django.views.decorators.clickjacking import xframe_options_sameorigin
from apps.accounts.models import User
from apps.dashboard import services

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
            return None, redirect("dashboard:admin_index")
        elif user.user_role == User.RoleChoices.RESPONDER:
            return None, redirect("dashboard:index")
        else:
            request.session.flush()
            return None, redirect("accounts:login")

    print("DEBUG: User passed all checks. Allowing access.") # <-- ADD THIS
    return user, None


# --- Main Dashboards ---

def index(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.RESPONDER)
    if redirect_response:
        return redirect_response

    return render(request, "dashboard/responder_index.html", services.responder_context(request, user))

def dashboard_general(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    return render(request, "dashboard/dashboard.html", {"user": user})

def admin_index(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
    if redirect_response:
        return redirect_response
        
    return render(request, "dashboard/admin_index.html", services.admin_context(request, user))

def call_logs(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response
        
    return render(request, "dashboard/call_logs.html", {"user": user})

def call_logs_admin(request):
    user, redirect_response = _get_session_user(request, required_role=User.RoleChoices.ADMIN)
    if redirect_response:
        return redirect_response

    return render(request, "dashboard/call_logs_admin.html", {"user": user})


def dongle_config(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    return render(request, "dashboard/dongle_config.html", {"user": user})


@xframe_options_sameorigin
def dongle_engine(request):
    """Minimal background page that owns mic capture, audio routing, and recording."""
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    return render(request, "dashboard/dongle_engine.html", {"user": user})