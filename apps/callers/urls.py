from django.urls import path
from django.views.generic import TemplateView

app_name = 'callers'

urlpatterns = [
    path('', TemplateView.as_view(template_name='callers/list.html'), name='list'),
    path('database/', TemplateView.as_view(template_name='callers/database.html'), name='database'),
]