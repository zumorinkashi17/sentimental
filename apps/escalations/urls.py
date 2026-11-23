from django.urls import path

from . import views

app_name = "escalations"

urlpatterns = [
    path("", views.queue, name="queue"),
    path("new/", views.new_escalation, name="new"),
    path("<int:escalation_id>/", views.detail, name="detail"),
    path("<int:escalation_id>/assign/", views.assign, name="assign"),
    path("<int:escalation_id>/acknowledge/", views.acknowledge, name="acknowledge"),
    path("<int:escalation_id>/request-info/", views.request_info, name="request_info"),
    path("<int:escalation_id>/provide-info/", views.provide_info, name="provide_info"),
    path("<int:escalation_id>/complete/", views.complete, name="complete"),
    path("<int:escalation_id>/cancel/", views.cancel, name="cancel"),
]
