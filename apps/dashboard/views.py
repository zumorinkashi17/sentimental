from django.shortcuts import render, redirect
from django.views.decorators.clickjacking import xframe_options_sameorigin
from apps.accounts.models import User
from apps.dashboard import services

def _get_session_user(request, required_role=None):
    """Return (user, None) or (None, redirect_response).

    The resolved user is cached on the request as ``_sentimental_user`` so the
    ``user_profile`` context processor can reuse it instead of issuing a second
    lookup while rendering the template.
    """
    if not hasattr(request, "_sentimental_user"):
        user_id = request.session.get("user_id")
        if not user_id:
            return None, redirect("accounts:login")

        try:
            request._sentimental_user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            request.session.flush()
            return None, redirect("accounts:login")

    user = request._sentimental_user

    if user.user_status != User.StatusChoices.ACTIVE:
        request.session.flush()
        return None, redirect("accounts:login")

    if required_role and user.user_role != required_role:
        if user.user_role == User.RoleChoices.ADMIN:
            return None, redirect("dashboard:admin_index")
        elif user.user_role == User.RoleChoices.RESPONDER:
            return None, redirect("dashboard:index")
        else:
            request.session.flush()
            return None, redirect("accounts:login")

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