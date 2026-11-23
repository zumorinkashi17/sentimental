from django import forms

from apps.accounts.models import User
from apps.escalations.models import CallerEscalation, EscalationAssessment


class EscalationCreateForm(forms.Form):
    urgency = forms.ChoiceField(
        choices=CallerEscalation.UrgencyChoices.choices,
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    observations = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 5}),
        label="Responder judgment and reason for escalation",
    )
    assigned_to = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Unassigned",
        widget=forms.Select(attrs={'class': 'form-input'}),
        label="Assign to mental health professional (optional)",
        help_text="Leave blank if a manager should assign the professional.",
    )


class AssignmentForm(forms.Form):
    assigned_to = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={'class': 'form-input'}),
        label="Mental health professional",
    )


class NoteForm(forms.Form):
    note = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 4}),
        label="Note",
    )


class AssessmentForm(forms.Form):
    findings = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 5}),
        label="Assessment findings",
    )
    recommendations = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 5}),
        label="Recommendations",
    )
    follow_up = forms.ChoiceField(
        choices=EscalationAssessment.FollowUpChoices.choices,
        widget=forms.Select(attrs={'class': 'form-input'}),
    )


class CancelForm(forms.Form):
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
        label="Reason (optional)",
    )
