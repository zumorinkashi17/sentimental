from django.urls import path
from . import views

app_name = 'heatmap'

urlpatterns = [
    path('map/', views.map_view, name='map'),
]
