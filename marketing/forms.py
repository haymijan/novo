from django import forms
from .models import Coupon, GiftCard

class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ['code', 'discount_type', 'discount_value', 'min_purchase_amount', 'valid_to', 'usage_limit', 'active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. SUMMER2025'}),
            'discount_type': forms.Select(attrs={'class': 'form-select'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control'}),
            'min_purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'valid_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'usage_limit': forms.NumberInput(attrs={'class': 'form-control'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class GiftCardForm(forms.ModelForm):
    class Meta:
        model = GiftCard
        fields = ['initial_value', 'customer', 'expiry_date']
        widgets = {
            'initial_value': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Amount'}),
            'customer': forms.Select(attrs={'class': 'form-control select2'}), # যদি কাস্টমার লিঙ্ক করতে চান
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }