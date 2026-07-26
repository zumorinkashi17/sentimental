from django.urls import path
from django.views.generic import TemplateView

app_name = 'reports'

urlpatterns = [
    path('generate/', TemplateView.as_view(template_name='reports/generate.html'), name='generate'),
]