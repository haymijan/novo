# pos/forms.py
from django import forms
from decimal import Decimal

class ReconciliationLineForm(forms.Form):
    """
    প্রতিটি পেমেন্ট মেথডের জন্য সিস্টেমের হিসাব এবং প্রকৃত গণনার ফর্ম।
    """
    payment_method_id = forms.IntegerField(widget=forms.HiddenInput())
    payment_method_name = forms.CharField(widget=forms.HiddenInput())
    
    expected_amount = forms.DecimalField(
        disabled=True, 
        required=False, 
        widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': True})
    )
    
    counted_amount = forms.DecimalField(
        label="Counted Amount", 
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    
    difference = forms.DecimalField(
        disabled=True, 
        required=False, 
        widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': True})
    )

# ফর্মসেট ব্যবহার করে একাধিক পেমেন্ট মেথড একসাথে দেখানো হবে
ReconciliationFormSet = forms.formset_factory(ReconciliationLineForm, extra=0)