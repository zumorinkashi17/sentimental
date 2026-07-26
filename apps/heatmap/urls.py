from django.urls import path
from django.views.generic import TemplateView

app_name = 'heatmap'

urlpatterns = [
    path('map/', TemplateView.as_view(template_name='heatmap/map.html'), name='map'),
]