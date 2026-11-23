from django.db import models
from django.utils import timezone

from apps.accounts.models import User
from apps.callers.models import CallSession


class CallerEscalation(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        ASSIGNED = 'Assigned', 'Assigned'
        UNDER_REVIEW = 'Under Review', 'Under Review'
        NEEDS_INFO = 'Needs Info', 'Needs Info'
        COMPLETED = 'Completed', 'Completed'
        CANCELLED = 'Cancelled', 'Cancelled'

    class UrgencyChoices(models.TextChoices):
        ROUTINE = 'Routine', 'Routine'
        PRIORITY = 'Priority', 'Priority'
        URGENT = 'Urgent', 'Urgent'

    escalation_id = models.AutoField(primary_key=True)
    session = models.ForeignKey(
        CallSession,
        on_delete=models.CASCADE,
        related_name='escalations',
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='requested_escalations',
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='assigned_escalations',
        null=True,
        blank=True,
        limit_choices_to={'user_role': User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL},
    )
    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )
    urgency = models.CharField(
        max_length=50,
        choices=UrgencyChoices.choices,
        default=UrgencyChoices.ROUTINE,
    )
    observations = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'caller_escalation'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='esc_status_created_idx'),
            models.Index(fields=['assigned_to', 'status', 'created_at'], name='esc_assignee_status_idx'),
            models.Index(fields=['session', 'created_at'], name='esc_session_created_idx'),
        ]

    @property
    def display_id(self):
        year = self.created_at.year if self.created_at else timezone.now().year
        return f"ESC-{year}-{self.pk:04d}" if self.pk else f"ESC-{year}-NEW"

    def __str__(self):
        return f"{self.display_id} ({self.status})"


class EscalationAssessment(models.Model):
    class FollowUpChoices(models.TextChoices):
        URGENT_REFERRAL = 'Urgent referral', 'Urgent referral'
        SCHEDULED_FOLLOW_UP = 'Scheduled follow-up', 'Scheduled follow-up'
        NO_FURTHER_ACTION = 'No further action', 'No further action'

    assessment_id = models.AutoField(primary_key=True)
    escalation = models.ForeignKey(
        CallerEscalation,
        on_delete=models.CASCADE,
        related_name='assessments',
    )
    assessed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='escalation_assessments',
    )
    findings = models.TextField()
    recommendations = models.TextField()
    follow_up = models.CharField(
        max_length=50,
        choices=FollowUpChoices.choices,
        default=FollowUpChoices.SCHEDULED_FOLLOW_UP,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'escalation_assessment'
        ordering = ['-created_at']

    def __str__(self):
        return f"Assessment for {self.escalation_id}"


class EscalationEvent(models.Model):
    class EventTypeChoices(models.TextChoices):
        CREATED = 'Created', 'Created'
        ASSIGNED = 'Assigned', 'Assigned'
        ACKNOWLEDGED = 'Acknowledged', 'Acknowledged'
        INFO_REQUESTED = 'Info Requested', 'Info Requested'
        INFO_PROVIDED = 'Info Provided', 'Info Provided'
        ASSESSED = 'Assessed', 'Assessed'
        STATUS_CHANGED = 'Status Changed', 'Status Changed'
        CANCELLED = 'Cancelled', 'Cancelled'

    event_id = models.AutoField(primary_key=True)
    escalation = models.ForeignKey(
        CallerEscalation,
        on_delete=models.CASCADE,
        related_name='events',
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='escalation_events',
    )
    event_type = models.CharField(max_length=50, choices=EventTypeChoices.choices)
    from_status = models.CharField(
        max_length=50,
        choices=CallerEscalation.StatusChoices.choices,
        null=True,
        blank=True,
    )
    to_status = models.CharField(
        max_length=50,
        choices=CallerEscalation.StatusChoices.choices,
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'escalation_event'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['escalation', 'created_at'], name='esc_event_esc_created_idx'),
        ]

    def __str__(self):
        return f"{self.event_type}: {self.escalation_id}"
