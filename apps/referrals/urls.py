from django.urls import path
from . import views

app_name = 'referrals'

urlpatterns = [
    path('directory/', views.directory_view, name='directory'),
    path('manage/', views.manage_view, name='manage'),
    path('api/professionals/', views.professionals_api, name='professionals_api'),
]