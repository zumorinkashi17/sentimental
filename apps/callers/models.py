from django.db import connection, models, transaction
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr
from apps.accounts.models import User
from apps.schedules.models import ShiftCatalog

SESSION_ID_PREFIX = 'TPCB10-'
# Fixed key for a transaction-scoped advisory lock that serialises session-ID
# allocation on PostgreSQL. Without it two concurrent saves could read the same
# max and try to insert the same primary key.
_SESSION_ID_LOCK_KEY = 0x53454E54


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

    @classmethod
    def _next_session_number(cls):
        """Return the next integer session number stored in the database.

        The numeric suffix is extracted and compared as an integer rather than
        as a string, so IDs keep incrementing correctly past 9999 (a plain
        ``order_by('-session_id')`` sort would break at five digits).
        """
        current_max = (
            cls.objects
            .filter(session_id__regex=rf'^{SESSION_ID_PREFIX}[0-9]+$')
            .aggregate(
                max_number=Max(
                    Cast(
                        Substr('session_id', len(SESSION_ID_PREFIX) + 1),
                        output_field=IntegerField(),
                    )
                )
            )['max_number']
        )
        return (current_max or 0) + 1

    @classmethod
    def next_session_preview(cls):
        """Formatted session ID the next saved call would receive."""
        return f"{SESSION_ID_PREFIX}{cls._next_session_number():04d}"

    def save(self, *args, **kwargs):
        # Only generate a new ID if this is a new record
        if self.session_id:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            # Serialise ID allocation across concurrent inserts on PostgreSQL.
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute(
                        'SELECT pg_advisory_xact_lock(%s)', [_SESSION_ID_LOCK_KEY]
                    )
            self.session_id = f"{SESSION_ID_PREFIX}{self._next_session_number():04d}"
            super().save(*args, **kwargs)
        
    class Meta:
        db_table = 'call_session'
        indexes = [
            models.Index(fields=['session_call_date', 'session_time_called'], name='cs_date_time_idx'),
            models.Index(fields=['user', 'session_call_date', 'session_time_called'], name='cs_user_dt_idx'),
            models.Index(fields=['caller', 'session_call_date', 'session_time_called'], name='cs_caller_dt_idx'),
        ]


class CallTranscript(models.Model):
    transcript_id = models.AutoField(primary_key=True)
    session = models.ForeignKey(CallSession, on_delete=models.CASCADE,null=True, blank=True)
    transcript_text = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'call_transcript'