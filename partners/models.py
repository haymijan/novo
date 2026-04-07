# partners/models.py

from django.db import models
from django.db.models import Sum

class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self): return self.name

    class Meta:
        db_table = 'inventory_supplier'

class Customer(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to='customers/', blank=True, null=True)
    customer_type = models.CharField(max_length=50, default='Retail')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self): return self.name

    # --- Properties (Renamed to avoid conflict with View Annotations) ---

    @property
    def get_total_sales(self):
        """কাস্টমারের মোট অর্ডারের টাকার পরিমাণ"""
        # যদি ভিউ থেকে অ্যানোটেশন করা থাকে, তবে সেটিই রিটার্ন করবে (Performance Optimization)
        if hasattr(self, 'total_sales_amount'):
            return self.total_sales_amount
        # না থাকলে ক্যালকুলেট করবে
        total = self.salesorder_set.aggregate(total=Sum('total_amount'))['total']
        return total or 0

    @property
    def get_total_received(self):
        """কাস্টমারের মোট জমার পরিমাণ (Payments)"""
        if hasattr(self, 'total_received_amount'):
            return self.total_received_amount
            
        from sales.models import SalesPayment
        total = SalesPayment.objects.filter(sales_order__customer=self).aggregate(total=Sum('amount'))['total']
        return total or 0

    @property
    def get_wallet_balance(self):
        """গিফট কার্ডের মোট ব্যালেন্স"""
        total = sum(card.current_balance for card in self.giftcard_set.filter(is_active=True))
        return total

    @property
    def get_current_due(self):
        """বর্তমান বকেয়া (মোট সেলস - মোট জমা)"""
        return self.get_total_sales - self.get_total_received

    class Meta:
        db_table = 'inventory_customer'
        ordering = ['-created_at']