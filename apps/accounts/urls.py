from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/",          views.login_view,          name="login"),
    path("logout/",         views.logout_view,         name="logout"),
    path("profile/",        views.profile_view,        name="profile"),
    path("manage/",         views.manage_users,        name="manage"),
    
    path("accounts/add/",                views.add_responder,  name="add_responder"),
    path("setup/",                       views.setup_account_view, name="setup_account"),
    path("setup/process/",               views.process_setup_view, name="process_setup"),
    path("accounts/<int:user_id>/",      views.get_responder,  name="get_responder"),
    path("accounts/<int:user_id>/edit/", views.edit_responder, name="edit_responder"),
    path("change-password/", views.change_password_view, name="change_password"),

    path("password-reset/", views.password_reset_view, name="password_reset"),
    path("reset-password/", views.reset_password_view, name="reset_password"),
    path("reset-password/process/", views.process_reset_password_view, name="process_reset_password"),
]