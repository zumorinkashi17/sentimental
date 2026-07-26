from django.urls import path
from django.views.generic import TemplateView

app_name = 'schedules'

urlpatterns = [
    path('calendar/', TemplateView.as_view(template_name='schedules/calendar.html'), name='calendar'),
    path('admin-calendar/', TemplateView.as_view(template_name='schedules/admin_calendar.html'), name='admin_calendar'),
]