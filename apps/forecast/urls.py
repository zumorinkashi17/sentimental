from django.urls import path
from django.views.generic import TemplateView

app_name = 'forecast'

urlpatterns = [
    path('prediction/', TemplateView.as_view(template_name='forecast/prediction.html'), name='prediction'),
]