from django.urls import path
from django.views.generic import TemplateView

app_name = 'documentation'

urlpatterns = [
    path('history/', TemplateView.as_view(template_name='documentation/history.html'), name='history'),
    path('master/', TemplateView.as_view(template_name='documentation/master_history.html'), name='master_history'),
    path('admin-history/', TemplateView.as_view(template_name='documentation/master_history.html'), name='admin_history'),
]