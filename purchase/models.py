# purchase/models.py
from django.db import models
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from products.models import Product
from partners.models import Supplier
from stock.models import Warehouse, Location
from stock.models import LotSerialNumber

#==================================================


class ProductSupplier(models.Model):
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='supplier_prices')
    supplier = models.ForeignKey('partners.Supplier', on_delete=models.CASCADE, related_name='supplied_products')
    supplier_product_code = models.CharField(max_length=100, blank=True, null=True, help_text="Supplier's internal product code")
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at which this product is purchased from the supplier")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'supplier')
        db_table = 'inventory_productsupplier'
        verbose_name_plural = "Product Suppliers"

    def __str__(self):
        return f"{self.product.name} from {self.supplier.name}"

class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('purchase_request', 'Purchase Request'),
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('partially_received', 'Partially Received'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ]
    
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchase_orders', null=True, blank=True)
    
    warehouse = models.ForeignKey(
        Warehouse, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='purchase_orders'
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_orders_created'
    )
    
    order_date = models.DateTimeField(auto_now_add=True)
    expected_delivery_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='purchase_request')
    notes = models.TextField(blank=True, null=True)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"PO-{self.pk} for {self.supplier.name if self.supplier else 'N/A'}"
    
    def update_status(self):
        """
        প্রাপ্ত আইটেমের উপর ভিত্তি করে পারচেজ অর্ডারের স্ট্যাটাস আপডেট করে।
        """
        total_ordered = self.items.aggregate(total=Sum('quantity'))['total'] or 0
        total_received = self.items.aggregate(total=Sum('quantity_received'))['total'] or 0

        if total_received >= total_ordered:
            self.status = 'received'
        elif total_received > 0:
            self.status = 'partially_received'
        
        self.save(update_fields=['status'])

class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='purchase_order_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_received = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.product.name} ({self.quantity} pcs)"

class StockTransferRequest(models.Model):
    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('in_transit', 'In Transit'),
        ('received', 'Received'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='transfer_requests')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='transfer_requests')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_transferred = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="The actual quantity sent from the source warehouse.")
    quantity_received = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="The actual quantity received at the destination warehouse.")
    
    dispatched_lot = models.ForeignKey(
        LotSerialNumber, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='transfer_dispatches',
        help_text="The specific lot from which stock was dispatched."
    )

    source_warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='source_transfers')
    destination_warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='destination_transfers')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='requested')
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Transfer Request #{self.id} for {self.product.name}"

    class Meta:
        db_table = 'inventory_stock_transfer_request'
        verbose_name = "Stock Transfer Request"
        verbose_name_plural = "Stock Transfer Requests"

class PurchaseReturn(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('shipped', 'Shipped to Supplier'),
        ('waiting_replacement', 'Waiting for Replacement'),
        ('completed', 'Completed'),
    ]

    RETURN_REASON_CHOICES = [
        ('damaged', 'Damaged Goods'),
        ('expired', 'Expired Goods'),
        ('wrong_item', 'Wrong Item Received'),
        ('quality_issue', 'Quality Issue'),
        ('overstock', 'Overstock'),
        ('other', 'Other'),
    ]

    RETURN_TYPE_CHOICES = [
        ('credit', 'Return for Credit'),
        ('exchange', 'Return for Exchange'),
    ]

    return_type = models.CharField(
        max_length=10,
        choices=RETURN_TYPE_CHOICES,
        default='credit',
        verbose_name="Return Type"
    )

    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, related_name='purchase_returns')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchase_returns')
    
    original_purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='returns')
    return_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    return_reason = models.CharField(max_length=50, choices=RETURN_REASON_CHOICES)
    notes = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return f"Return #{self.pk} to {self.supplier.name}"

    class Meta:
        verbose_name = "Purchase Return"
        verbose_name_plural = "Purchase Returns"


class PurchaseReturnItem(models.Model):
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    lot_serial = models.ForeignKey(LotSerialNumber, on_delete=models.SET_NULL, null=True, blank=True, help_text="The specific lot being returned", related_name='returned_item')
    
    received_lot_serial = models.ForeignKey(
        LotSerialNumber, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        help_text="The new lot received as exchange",
        related_name='received_as_exchange_item'
    )

    @property
    def total_cost(self):
        return self.quantity * self.unit_price
    
    def __str__(self):
        return f"{self.quantity} x {self.product.name} for Return #{self.purchase_return.pk}"
    
class SupplierCreditNote(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'), # ক্রেডিট ব্যবহার করা যাবে
        ('Applied', 'Applied'),     # ক্রেডিট ব্যবহার করা হয়েছে
        ('Cancelled', 'Cancelled'), # ক্রেডিট বাতিল করা হয়েছে
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='credit_notes')
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.SET_NULL, null=True, blank=True, related_name='credit_notes')
    created_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_available = models.DecimalField(max_digits=12, decimal_places=2) # কতটুকু ব্যবহারযোগ্য আছে
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_credit_notes')

    # এই ক্রেডিট নোটটি কোন পেমেন্টে ব্যবহার করা হয়েছে তা ট্র্যাক করার জন্য
    applied_payment = models.ForeignKey('ap.BillPayment', on_delete=models.SET_NULL, null=True, blank=True, related_name='applied_credits')

    def __str__(self):
        return f"Credit Note #{self.pk} for {self.supplier.name} - Amount: {self.amount}"

    def save(self, *args, **kwargs):
        if self._state.adding: # নতুন তৈরি করার সময়
            self.amount_available = self.amount
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Supplier Credit Note"
        verbose_name_plural = "Supplier Credit Notes"