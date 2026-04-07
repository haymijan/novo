# forms.py

from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth import get_user_model # এটি যোগ করুন

class CustomPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = self.cleaned_data.get('email')
        User = get_user_model() # এটি যোগ করুন
        if not User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email address is not registered.")
        return email