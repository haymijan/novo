# pos/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from products.models import Product
from partners.models import Customer
from stock.models import Warehouse, LotSerialNumber
from finance.cash.models import CashRegister
from finance.banking.models import PaymentMethod
from django.db.models import Sum
from marketing.models import GiftCard

class POSSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    cash_register = models.ForeignKey(CashRegister, on_delete=models.PROTECT)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[('open', 'Open'), ('closed', 'Closed')], default='open')
    
    opening_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    expected_balance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    counted_balance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    difference = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"Session for {self.user.username} at {self.cash_register.name} ({self.status})"

class POSOrder(models.Model):
    pos_session = models.ForeignKey(POSSession, on_delete=models.PROTECT, related_name='pos_orders')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True)
    order_date = models.DateTimeField(default=timezone.now)

    status = models.CharField(
        max_length=20, 
        choices=[('pending', 'Pending'), ('paid', 'Paid'), ('cancelled', 'Cancelled')], 
        default='pending'
    ) 
    
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    round_off_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    @property
    def total_paid(self):
        return self.payments.aggregate(total=Sum('amount'))['total'] or 0
    
    @property
    def change_due(self):
        change = self.total_paid - self.net_amount
        return change if change > 0 else 0

    def __str__(self):
        return f"POS Order {self.id} on {self.order_date.strftime('%Y-%m-%d')}"

class POSOrderItem(models.Model):
    pos_order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    lot_serial = models.ForeignKey(LotSerialNumber, on_delete=models.SET_NULL, null=True, blank=True)
    
    @property
    def subtotal(self):
        return self.quantity * self.unit_price

class POSOrderPayment(models.Model):
    pos_order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name='payments')
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    gift_card = models.ForeignKey(GiftCard, on_delete=models.SET_NULL, null=True, blank=True, related_name='usages')
    
    def __str__(self):
        return f"Payment for POS Order {self.pos_order.id} via {self.payment_method.name}"