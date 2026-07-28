from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'documentation'

urlpatterns = [
    path('history/', views.user_history_view, name='history'),
    path('master/', views.history_list_view, name='master_history'),
    path('admin-history/', views.history_list_view, name='admin_history'),
]