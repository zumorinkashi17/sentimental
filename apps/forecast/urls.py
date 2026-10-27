from django.urls import path

from . import views

app_name = 'forecast'

urlpatterns = [
    path('prediction/', views.prediction, name='prediction'),
    path('prediction/generate/', views.generate, name='generate'),
    path('prediction/export/', views.export, name='export'),
]
