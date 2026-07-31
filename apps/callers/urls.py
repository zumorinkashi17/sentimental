from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'callers'

urlpatterns = [
    path('', views.list_view, name='list'),
    path('database/', views.database_view, name='database'),
    path('api/save-session/', views.save_call_documentation, name='save_session'),
]