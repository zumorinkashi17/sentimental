from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    # Main dashboards
    path("admin/",          views.admin_dashboard,   name="admin_dashboard"),
    path("responder/",      views.responder_dashboard, name="responder_dashboard"),
    
    # Other pages
    path("",                views.index,             name="index"),
    path("home/",           views.dashboard_general, name="dashboard_general"),
    path("admin/index/",    views.admin_index,       name="admin_index"),
    
    # Call logs
    path("call-logs/",      views.call_logs,         name="call_logs"),
    path("admin/call-logs/",views.call_logs_admin,   name="call_logs_admin"),
]