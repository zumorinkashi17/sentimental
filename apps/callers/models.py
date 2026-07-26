from django.db import models
from apps.accounts.models import User
from apps.schedules.models import ShiftCatalog


class Caller(models.Model):
    caller_id = models.AutoField(primary_key=True)
    caller_name = models.CharField(max_length=255, default="Anonymous")
    caller_gender = models.CharField(max_length=50, blank=True, null=True)
    caller_civil_status = models.CharField(max_length=50, blank=True, null=True)
    caller_number = models.IntegerField(blank=True, null=True)
    caller_age = models.IntegerField(blank=True, null=True)
    caller_location = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'caller'


class CallSession(models.Model):
    class RiskChoices(models.TextChoices):
        LOW = 'Low', 'Low'
        MEDIUM = 'Medium', 'Medium'
        HIGH = 'High', 'High'

    session_id = models.CharField(max_length=255, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    caller = models.ForeignKey(Caller, on_delete=models.CASCADE)
    shift = models.ForeignKey(ShiftCatalog, on_delete=models.CASCADE)
    session_call_date = models.DateField()
    session_time_called = models.TimeField()
    session_time_ended = models.TimeField(blank=True, null=True)
    session_reason_for_calling = models.CharField(max_length=255, blank=True, null=True)
    session_risk_assessment = models.CharField(max_length=50, choices=RiskChoices.choices)
    session_intervention = models.TextField(blank=True, null=True)
    session_additional_comments = models.TextField(blank=True, null=True)
    session_summarization = models.TextField()

    class Meta:
        db_table = 'call_session'


class CallTranscript(models.Model):
    transcript_id = models.AutoField(primary_key=True)
    session = models.ForeignKey(CallSession, on_delete=models.CASCADE,null=True, blank=True)
    transcript_text = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'call_transcript'