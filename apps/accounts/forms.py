from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm

User = get_user_model()


class PasswordResetRequestForm(PasswordResetForm):
    email = forms.EmailField(
        label='Email Address',
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                'class': 'form-input',
                'placeholder': 'user@tawagpaglaum.org',
                'required': True,
                'autocomplete': 'email',
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        matching_users = User.objects.filter(email__iexact=email)
        if not matching_users.exists():
            raise forms.ValidationError('Email not found.')

        active_users = matching_users.filter(is_active=True)
        if not active_users.exists():
            raise forms.ValidationError('The account with this email is inactive.')

        return email
