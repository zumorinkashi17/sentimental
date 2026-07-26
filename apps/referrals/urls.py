from django.urls import path
from django.views.generic import TemplateView

app_name = 'referrals'

urlpatterns = [
    path('directory/', TemplateView.as_view(template_name='referrals/directory.html'), name='directory'),
    path('manage/', TemplateView.as_view(template_name='referrals/manage.html'), name='manage'),
]