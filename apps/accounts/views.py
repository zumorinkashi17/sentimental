import os
import secrets
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from supabase import create_client, Client
from .models import User, UserLog
from apps.callers.models import CallSession
from django.utils import timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_NAME = "image-bucket"

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.session.get('user_id'):
        return _redirect_by_role(request.session.get('user_role'))

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        next_url = request.POST.get("next") or request.GET.get("next") or ""

        user = None
        try:
            user = User.objects.get(user_email__iexact=email)
        except User.DoesNotExist:
            pass

        if user is None or not user.check_password(password):
            messages.error(request, "Invalid email or password.")
            return render(request, "accounts/login.html", {"next": next_url})

        if user.user_status != User.StatusChoices.ACTIVE:
            messages.error(
                request,
                "Your account is inactive. Please contact an administrator."
            )
            return render(request, "accounts/login.html", {"next": next_url})

        token = secrets.token_urlsafe(48)
        user_log = UserLog.objects.create(user=user, log_token=token)

        request.session["user_id"]     = user.user_id
        request.session["user_log_id"] = user_log.log_id
        request.session["user_role"]   = user.user_role
        request.session["user_name"]   = f"{user.user_first_name} {user.user_last_name}"
        request.session["user_email"]  = user.user_email
        request.session.set_expiry(60 * 60 * 8)  # 8 hours

        if next_url:
            return redirect(next_url)

        return _redirect_by_role(user.user_role)

    return render(request, "accounts/login.html", {
        "next": request.GET.get("next", "")
    })


def _upload_to_supabase(file_obj, file_name):
    try:
        file_data = file_obj.read()
        supabase.storage.from_(BUCKET_NAME).upload(
            file_name, 
            file_data, 
            {"content-type": file_obj.content_type}
        )
        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
        return public_url
    except Exception as e:
        print(f"Supabase Upload Error: {e}")
        return None

def manage_users(request):
    if request.session.get('user_role') != 'Admin':
        return redirect('dashboard:responder_dashboard')
        
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'all')

    current_user_id = request.session.get('user_id')
    
    users = User.objects.exclude(user_id=current_user_id)
    
    if search_query:
        users = users.filter(
            Q(user_first_name__icontains=search_query) |
            Q(user_last_name__icontains=search_query) |
            Q(user_email__icontains=search_query)
        )
        
    if status_filter != 'all':
        users = users.filter(user_status__iexact=status_filter)
        
    return render(request, "accounts/manage.html", {
        "users": users,
        "search_query": search_query,
        "status_filter": status_filter
    })

@require_http_methods(["POST"])
def add_responder(request):
    email = request.POST.get("email", "").strip().lower()
    
    logo_url = "https://svvqtysxursbauiqepbg.supabase.co/storage/v1/object/public/image-bucket/Sentimental-logo.png"
    
    def generate_email_html(url, is_reminder=False):
        title = "Set up your SentiMental Account"
        greeting_text = "An account has been created for you on the SentiMental platform."
        if is_reminder:
            title = "Set up your SentiMental Account (Reminder)"
            greeting_text = "This is a reminder to set up your account on the SentiMental platform."

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
        </head>
        <body style="margin:0; padding:0; background-color:#f8fcfb; font-family:'Inter', Arial, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="padding: 40px 0;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 6px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                            
                            <!-- Header / Logo -->
                            <tr>
                                <td align="center" style="padding: 40px 0 20px 0; background-color: #e6f7f4;">
                                    <img src="{logo_url}" alt="SentiMental" width="64" height="64" style="display:block; border-radius: 50%;">
                                </td>
                            </tr>
                            
                            <!-- Content -->
                            <tr>
                                <td style="padding: 30px 40px 10px 40px; color: #334155; font-size: 16px; line-height: 1.6;">
                                    <h2 style="color:#1e293b; text-align:center; font-size: 22px; margin-bottom: 20px;">Welcome to SentiMental</h2>
                                    <p style="margin-bottom: 16px;">Hello,</p>
                                    <p style="margin-bottom: 24px;">{greeting_text} Please click the button below to verify your email address and set up your password and profile details.</p>
                                </td>
                            </tr>
                            
                            <!-- Button -->
                            <tr>
                                <td align="center" style="padding: 10px 40px 40px 40px;">
                                    <a href="{url}" style="background-color:#00a67e; color:#ffffff; text-decoration:none; font-weight:bold; padding:14px 32px; border-radius:8px; display:inline-block; font-size:16px; box-shadow: 0 4px 6px rgba(0, 166, 126, 0.2);">
                                        Verify & Set Up Account
                                    </a>
                                </td>
                            </tr>
                            
                            <!-- Fallback Link & Footer -->
                            <tr>
                                <td style="padding: 0 40px 40px 40px; text-align: center;">
                                    <p style="font-size: 12px; color: #94a3b8; margin-bottom: 30px;">
                                        If the button doesn't work, copy and paste this link into your browser:<br>
                                        <a href="{url}" style="color: #00a67e; word-break: break-all;">{url}</a>
                                    </p>
                                    <div style="border-top: 1px solid #e2e8f0; padding-top: 20px;">
                                        <p style="font-size: 12px; color: #94a3b8; margin: 0;">If you did not expect this email, please ignore it.</p>
                                        <p style="font-size: 12px; color: #94a3b8; margin-top: 8px;">&copy; SentiMental</p>
                                    </div>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
    if User.objects.filter(user_email=email).exists():
        user = User.objects.get(user_email=email)
        
        if user.user_status == User.StatusChoices.ACTIVE:
            return JsonResponse({
                "success": False, 
                "message": "An active account with this email already exists."
            }, status=400)
        
        # Generate a NEW token and resend the email
        token = secrets.token_urlsafe(32)
        user.user_setup_token = token
        user.save()
        
        setup_url = request.build_absolute_uri(f"/accounts/setup/?token={token}")
        html_content = generate_email_html(setup_url, is_reminder=True)
        
        try:
            send_mail(
                subject="Set up your SentiMental Account (Reminder)",
                message=f"Please click the link to set up your account:\n\n{setup_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                html_message=html_content, 
                fail_silently=False,
            )
        except Exception as e:
            print(f"Email sending failed: {e}")
            return JsonResponse({"success": False, "message": "Failed to resend email. Check server logs."}, status=500)

        return JsonResponse({
            "success": True,
            "message": "This user hasn't set up their account yet. A new verification email has been sent."
        })

    token = secrets.token_urlsafe(32)
    
    user = User(
        user_email=email,
        user_role=User.RoleChoices.RESPONDER,
        user_status=User.StatusChoices.INACTIVE,
        user_setup_token=token
    )
    user.save()

    setup_url = request.build_absolute_uri(f"/accounts/setup/?token={token}")
    html_content = generate_email_html(setup_url, is_reminder=False)
    
    try:
        send_mail(
            subject="Set up your SentiMental Account",
            message=f"Please click the link to set up your account:\n\n{setup_url}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_content,
            fail_silently=False,
        )
    except Exception as e:
        print(f"Email sending failed: {e}")
        return JsonResponse({"success": False, "message": "Account created, but failed to send email. Check server logs."}, status=500)

    return JsonResponse({
        "success": True,
        "message": "Verification email sent successfully. The user can now check their inbox to set up their account."
    })

def setup_account_view(request):
    token = request.GET.get("token")
    if not token:
        messages.error(request, "Invalid setup link.")
        return redirect("accounts:login")
    
    try:
        user = User.objects.get(user_setup_token=token, user_status=User.StatusChoices.INACTIVE)
    except User.DoesNotExist:
        messages.error(request, "This setup link is invalid, expired, or the account is already active.")
        return redirect("accounts:login")

    return render(request, "accounts/setup_account.html", {"token": token})

@require_http_methods(["POST"])
def process_setup_view(request):
    token = request.POST.get("token")
    password = request.POST.get("password")
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    user_number = request.POST.get("user_number", "").strip()
    user_location = request.POST.get("user_location", "").strip()

    if not token or not password:
        return JsonResponse({"success": False, "message": "Token and password are required."}, status=400)

    try:
        user = User.objects.get(user_setup_token=token, user_status=User.StatusChoices.INACTIVE)
    except User.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invalid or expired token."}, status=400)

    # Update user details
    user.user_first_name = first_name
    user.user_last_name = last_name
    user.user_number = user_number
    user.user_location = user_location
    user.set_password(password)
    user.user_status = User.StatusChoices.ACTIVE
    user.user_setup_token = None 
    user.save()

    return JsonResponse({"success": True, "redirect_url": "/accounts/login/"})

def get_responder(request, user_id):
    user = get_object_or_404(User, user_id=user_id)
    data = {
        "success": True,
        "profile": {
            "profile_id": user.user_id,
            "first_name": user.user_first_name,
            "last_name": user.user_last_name,
            "email": user.user_email,
            "user_role": user.user_role,
            "user_status": user.user_status,
            "user_number": user.user_number or "",
            "user_location": user.user_location or "",
            "user_image": user.user_image or ""
        }
    }
    return JsonResponse(data)

@require_http_methods(["POST"])
def edit_responder(request, user_id):
    user = get_object_or_404(User, user_id=user_id)
    
    user.user_first_name = request.POST.get("first_name", user.user_first_name).strip()
    user.user_last_name = request.POST.get("last_name", user.user_last_name).strip()
    user.user_email = request.POST.get("email", user.user_email).strip().lower()
    user.user_number = request.POST.get("user_number", user.user_number).strip()
    user.user_location = request.POST.get("user_location", user.user_location).strip()
    
    user.user_role = request.POST.get("user_role", user.user_role)
    user.user_status = request.POST.get("user_status", user.user_status)
    
    if 'user_image' in request.FILES:
        user_image_file = request.FILES.get("user_image")
        ext = user_image_file.name.split('.')[-1]
        unique_filename = f"responder_{user.user_email.split('@')[0]}_{secrets.token_hex(8)}.{ext}"
        user.user_image = _upload_to_supabase(user_image_file, unique_filename)
        
    user.save()
    
    return JsonResponse({"success": True, "message": "Responder updated successfully."})

def profile_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('accounts:login')

    user = get_object_or_404(User, user_id=user_id)

    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        first_name    = request.POST.get('first_name', '').strip()
        last_name     = request.POST.get('last_name', '').strip()
        user_number   = request.POST.get('user_number', '').strip()
        user_location = request.POST.get('user_location', '').strip()
        new_password  = request.POST.get('new_password', '').strip()

        user.user_first_name = first_name
        user.user_last_name  = last_name
        user.user_number     = user_number
        user.user_location   = user_location
        
        if new_password:
            user.set_password(new_password)

        image_file = request.FILES.get('user_image')
        if image_file:
            ext = image_file.name.split('.')[-1]
            unique_filename = f"profile_{user.user_id}_{secrets.token_hex(8)}.{ext}"
            uploaded_url = _upload_to_supabase(image_file, unique_filename)
            if uploaded_url:
                user.user_image = uploaded_url

        user.save()

        # Update the session name if they changed it
        request.session['user_name'] = f"{user.user_first_name} {user.user_last_name}"

        return JsonResponse({
            'success': True, 
            'message': 'Profile updated successfully.', 
            'user_image': user.user_image or ''
        })

    calls_count = CallSession.objects.filter(user=user).count()

    return render(request, 'accounts/profile.html', {
        'user': user,
        'session_role': request.session.get('user_role', 'Responder'),
        'calls_count': calls_count
    })

@require_http_methods(["POST"])
def change_password_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({"success": False, "message": "You must be logged in."}, status=403)
        
    user = get_object_or_404(User, user_id=user_id)
    old_password = request.POST.get("old_password", "")
    new_password = request.POST.get("new_password", "")
    confirm_password = request.POST.get("confirm_password", "")

    if not user.check_password(old_password):
        return JsonResponse({"success": False, "message": "Your old password is incorrect."}, status=400)
    
    if new_password != confirm_password:
        return JsonResponse({"success": False, "message": "New passwords do not match."}, status=400)
        
    if len(new_password) < 8:
        return JsonResponse({"success": False, "message": "Password must be at least 8 characters."}, status=400)

    user.set_password(new_password)
    user.save()

    return JsonResponse({"success": True, "message": "Password changed successfully."})


def logout_view(request):
    log_id = request.session.get("user_log_id")
    if log_id:
        UserLog.objects.filter(log_id=log_id).update(log_time_out=timezone.now())
    request.session.flush()
    
    return redirect("accounts:login")


def password_reset_view(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        try:
            user = User.objects.get(user_email__iexact=email)
            token = secrets.token_urlsafe(32)
            user.user_setup_token = token
            user.save()
            
            reset_url = request.build_absolute_uri(f"/accounts/reset-password/?token={token}")
            logo_url = "https://svvqtysxursbauiqepbg.supabase.co/storage/v1/object/public/image-bucket/Sentimental-logo.png"
            
            html_content = f"""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"></head>
            <body style="margin:0; padding:0; background-color:#f8fcfb; font-family:'Inter', Arial, sans-serif;">
                <table width="100%" cellpadding="0" cellspacing="0" style="padding: 40px 0;">
                    <tr><td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 6px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                            <tr><td align="center" style="padding: 40px 0 20px 0; background-color: #e6f7f4;">
                                <img src="{logo_url}" alt="Sentimental" width="64" height="64" style="display:block; border-radius: 50%;">
                            </td></tr>
                            <tr><td style="padding: 30px 40px 10px 40px; color: #334155; font-size: 16px; line-height: 1.6;">
                                <h2 style="color:#1e293b; text-align:center; font-size: 22px; margin-bottom: 20px;">Reset Your Password</h2>
                                <p style="margin-bottom: 24px;">Hello,</p>
                                <p style="margin-bottom: 24px;">We received a request to reset your password for your SentiMental account. Click the button below to choose a new password.</p>
                            </td></tr>
                            <tr><td align="center" style="padding: 10px 40px 40px 40px;">
                                <a href="{reset_url}" style="background-color:#00a67e; color:#ffffff; text-decoration:none; font-weight:bold; padding:14px 32px; border-radius:8px; display:inline-block; font-size:16px; box-shadow: 0 4px 6px rgba(0, 166, 126, 0.2);">Reset Password</a>
                            </td></tr>
                            <tr><td style="padding: 0 40px 40px 40px; text-align: center;">
                                <p style="font-size: 12px; color: #94a3b8; margin-bottom: 30px;">
                                    If the button doesn't work, copy and paste this link into your browser:<br>
                                    <a href="{reset_url}" style="color: #00a67e; word-break: break-all;">{reset_url}</a>
                                </p>
                                <div style="border-top: 1px solid #e2e8f0; padding-top: 20px;">
                                    <p style="font-size: 12px; color: #94a3b8; margin: 0;">If you did not request a password reset, please ignore this email.</p>
                                </div>
                            </td></tr>
                        </table>
                    </td></tr>
                </table>
            </body></html>
            """
            
            send_mail(
                subject="Reset Your SentiMental Password",
                message=f"Please click the link to reset your password:\n\n{reset_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                html_message=html_content,
                fail_silently=True,
            )
        except User.DoesNotExist:
            pass
            
        return JsonResponse({"success": True, "message": "If an account with that email exists, a password reset link has been sent."})

    return render(request, "accounts/password_reset.html")

def reset_password_view(request):
    token = request.GET.get("token")
    if not token:
        messages.error(request, "Invalid reset link.")
        return redirect("accounts:login")
        
    try:
        # We don't care about status here, anyone with a valid token can reset
        user = User.objects.get(user_setup_token=token)
    except User.DoesNotExist:
        messages.error(request, "This reset link is invalid or has expired.")
        return redirect("accounts:login")

    return render(request, "accounts/reset_password.html", {"token": token})

@require_http_methods(["POST"])
def process_reset_password_view(request):
    token = request.POST.get("token")
    password = request.POST.get("password")
    confirm_password = request.POST.get("confirm_password")

    if not token or not password:
        return JsonResponse({"success": False, "message": "Token and password are required."}, status=400)

    if password != confirm_password:
        return JsonResponse({"success": False, "message": "Passwords do not match."}, status=400)
        
    if len(password) < 8:
        return JsonResponse({"success": False, "message": "Password must be at least 8 characters."}, status=400)

    try:
        user = User.objects.get(user_setup_token=token)
    except User.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invalid or expired token."}, status=400)

    user.set_password(password)
    user.user_setup_token = None
    user.save()

    return JsonResponse({"success": True, "redirect_url": "/accounts/login/"})


def _redirect_by_role(role):
    if role == User.RoleChoices.ADMIN:
        return redirect("dashboard:admin_dashboard")
    return redirect("dashboard:responder_dashboard")


