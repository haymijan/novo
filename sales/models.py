from django.db import models
from django.utils import timezone
from django.conf import settings
from stock.models import Warehouse, LotSerialNumber
from django.db.models import Sum, F, DecimalField
from decimal import Decimal
from partners.models import Customer

class SalesOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing (Warehouse)'),
        ('packaging', 'Packaging'),
        ('out_for_delivery', 'Out For Delivery'),
        ('delivered', 'Delivered'),
        ('partially_delivered', 'Partially Delivered'),
        ('cancelled', 'Cancelled'),
        ('returned', 'Returned'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
        ('unpaid', 'Unpaid'),
    ]

    sales_order_number = models.CharField(max_length=50, unique=True, editable=False, null=True, blank=True)
    customer = models.ForeignKey('partners.Customer', on_delete=models.SET_NULL, null=True, blank=True)
    order_date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="The user who created the sales order."
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="The branch/warehouse from which the sale was made."
    )
    expected_delivery_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    round_off_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Amount rounded off from the total (e.g., 0.05)"
    )

    paid_by_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    paid_by_card = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    payment_note = models.TextField(blank=True, null=True)
    selected_payment_method = models.ForeignKey(
        'banking.PaymentMethod',
        on_delete=models.SET_NULL,
        null=True, blank=True, 
        related_name='sales_orders'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True, help_text="General notes about the order")

    def save(self, *args, **kwargs):
        if not self.sales_order_number:
            last_order = SalesOrder.objects.all().order_by('id').last()
            if last_order:
                try:
                    last_id = int(last_order.sales_order_number.split('-')[1])
                    self.sales_order_number = 'SO-' + str(last_id + 1).zfill(6)
                except:
                    self.sales_order_number = 'SO-' + str(last_order.id + 1).zfill(6)
            else:
                self.sales_order_number = 'SO-000001'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sales_order_number} - {self.customer.name if self.customer else 'Guest'}"
    
    @property
    def net_amount(self):
        return self.total_amount
    
    def get_total_cost_price(self):
        total_cost = self.items.aggregate(
            total=Sum(F('quantity') * F('cost_price'), output_field=DecimalField())
        )['total']
        return total_cost or Decimal('0.00')

class SalesPayment(models.Model):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='payments')
    payment_method = models.ForeignKey('banking.PaymentMethod', on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True, help_text="Transaction ID or Check No")
    payment_date = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return f"Pay {self.amount} for {self.sales_order.sales_order_number}"

class Shipment(models.Model):
    STATUS_CHOICES = [
        ('packaging', 'In Packaging'),
        ('shipped', 'Shipped / Out for Delivery'),
        ('delivered', 'Delivered'),
    ]
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='shipments')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    tracking_number = models.CharField(max_length=100, blank=True)
    courier_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='packaging')
    created_at = models.DateTimeField(auto_now_add=True)
    shipped_date = models.DateTimeField(null=True, blank=True)
    delivered_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Shipment #{self.id} for {self.sales_order.sales_order_number}"

class SalesOrderItem(models.Model):
    sales_order = models.ForeignKey(SalesOrder, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE)

    issued_gift_card = models.ForeignKey(
        'marketing.GiftCard', 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        help_text="Fulfillment এর সময় এই ফিল্ডটি পূরণ করতে হবে"
    )

    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    quantity_fulfilled = models.PositiveIntegerField(default=0)
    
    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

class SalesOrderItemAllocation(models.Model):
    sales_order_item = models.ForeignKey(SalesOrderItem, related_name='allocations', on_delete=models.CASCADE)
    lot = models.ForeignKey(LotSerialNumber, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    allocated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Allocated {self.quantity} from {self.lot.lot_number}"

class SalesReturn(models.Model):
    RETURN_TYPE_CHOICES = [
        ('refund', 'Refund (Money Back)'),
        ('exchange', 'Exchange (Credit/Replace)'),
    ]

    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='returns', null=True, blank=True)

    customer = models.ForeignKey(
        'partners.Customer', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='salesreturn'  
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )

    return_date = models.DateTimeField(default=timezone.now)
    reason = models.TextField()
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True)
    return_type = models.CharField(max_length=20, choices=RETURN_TYPE_CHOICES, default='refund')
    total_refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    def __str__(self):
        return f"Return #{self.id} for SO-{self.sales_order.sales_order_number if self.sales_order else 'N/A'}"

class SalesReturnItem(models.Model):
    sales_return = models.ForeignKey(SalesReturn, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    lot_sold_from = models.ForeignKey(LotSerialNumber, on_delete=models.SET_NULL, null=True, blank=True)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"