from django.db import models
from django.utils import timezone
from partners.models import Customer
import random
import string

class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (Tk)'),
    ]

    code = models.CharField(max_length=20, unique=True, help_text="Unique Code (e.g. SUMMER25)")
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default='fixed')
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, help_text="Discount Amount or Percentage")
    
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Minimum purchase required")
    max_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Max cap for percentage discount")
    
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField()
    usage_limit = models.PositiveIntegerField(default=100, help_text="Total times coupon can be used")
    used_count = models.PositiveIntegerField(default=0)
    
    active = models.BooleanField(default=True)

    def is_valid(self):
        now = timezone.now()
        return self.active and self.valid_from <= now <= self.valid_to and self.used_count < self.usage_limit

    def __str__(self):
        return f"{self.code} - {self.discount_value} ({self.get_discount_type_display()})"

class GiftCard(models.Model):
    code = models.CharField(max_length=50, unique=True, editable=False, help_text="Auto-generated 16 digit code")
    initial_value = models.DecimalField(max_digits=10, decimal_places=2)
    current_balance = models.DecimalField(max_digits=10, decimal_places=2)
    
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, help_text="If assigned to a specific customer")
    
    created_at = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_unique_code()
        if self._state.adding:
            self.current_balance = self.initial_value
        super().save(*args, **kwargs)

    def generate_unique_code(self):
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
            formatted_code = '-'.join([code[i:i+4] for i in range(0, len(code), 4)])
            if not GiftCard.objects.filter(code=formatted_code).exists():
                return formatted_code

    def __str__(self):
        return f"GC-{self.code} (Bal: {self.current_balance})"

class GiftCardTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('purchase', 'Purchase (Debit)'),
        ('reload', 'Reload/Issue (Credit)'),
        ('refund', 'Refund (Credit)'),
    )
    
    gift_card = models.ForeignKey(GiftCard, related_name='transactions', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    date = models.DateTimeField(default=timezone.now)
    reference = models.CharField(max_length=100, blank=True, help_text="Order ID or Note")
    
    def __str__(self):
        return f"{self.gift_card.code} - {self.transaction_type} - {self.amount}"