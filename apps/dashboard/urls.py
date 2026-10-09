from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    # Main dashboards
    path("admin/index/",    views.admin_index,       name="admin_index"),

    # Other pages
    path("",                views.index,             name="index"),
    path("home/",           views.dashboard_general, name="dashboard_general"),
    path("dongle/",         views.dongle_config,     name="dongle_config"),
    path("dongle/engine/",  views.dongle_engine,     name="dongle_engine"),

    # Call logs
    path("call-logs/",      views.call_logs,         name="call_logs"),
    path("admin/call-logs/",views.call_logs_admin,   name="call_logs_admin"),
]