from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'schedules'

urlpatterns = [
    path('calendar/', TemplateView.as_view(template_name='schedules/calendar.html'), name='calendar'),
    path('admin-calendar/', views.admin_calendar_view, name='admin_calendar'),
    path('api/add-shift/', views.add_shift, name='add_shift'),
]