from django import forms
from .models import User

class PhoneLoginForm(forms.Form):
    phone = forms.CharField(
        label="Mobile Number",
        max_length=15,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter mobile number (e.g. 33334444)'})
    )

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not User.objects.filter(phone=phone).exists():
            raise forms.ValidationError("This phone number is not registered.")
        return phone

class OTPVerificationForm(forms.Form):
    otp = forms.CharField(
        label="OTP Code",
        max_length=4,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter 4-digit OTP'})
    )