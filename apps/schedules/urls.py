from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'schedules'

urlpatterns = [
   path('calendar/', views.responder_schedule_view, name='calendar'),
    path('api/submit-dayoff/', views.submit_dayoff_request, name='submit_dayoff_request'),

    path('admin-calendar/', views.admin_calendar_view, name='admin_calendar'),
    path('api/add-shift/', views.add_shift, name='add_shift'),
    path('save-schedule/', views.save_schedule, name='save_schedule'),
    path('update-days-off/', views.update_schedule_days_off, name='update_schedule_days_off'),
    path('update-dayoff-status/', views.update_dayoff_status, name='update_dayoff_status'),
    path('api/schedules/user/<int:user_id>/', views.api_user_schedule, name='api_user_schedule'),
]