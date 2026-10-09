from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('api/', views.get_notifications, name='get_notifications'),
    path('mark-read/', views.mark_read, name='mark_read'),
]
