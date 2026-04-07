# sales/admin.py

from django.contrib import admin
from .models import SalesOrder, SalesOrderItem, SalesReturn, SalesReturnItem, SalesPayment, Shipment, SalesOrderItemAllocation

# ===================================================================
# ইনলাইন ক্লাসেস (Inline Classes)
# ===================================================================

class SalesOrderItemAllocationInline(admin.TabularInline):
    model = SalesOrderItemAllocation
    extra = 0
    readonly_fields = ('lot', 'quantity', 'allocated_at')
    can_delete = False

class SalesOrderItemInline(admin.TabularInline):
    model = SalesOrderItem
    extra = 0
    # 'lot_sold_from' বাদ দেওয়া হয়েছে কারণ এটি এখন Allocation মডেলে আছে
    fields = ('product', 'quantity', 'unit_price', 'subtotal', 'quantity_fulfilled')
    readonly_fields = ('subtotal', 'quantity_fulfilled')
    can_delete = False

class SalesPaymentInline(admin.TabularInline):
    model = SalesPayment
    extra = 0
    readonly_fields = ('payment_date', 'recorded_by')
    can_delete = False

class ShipmentInline(admin.TabularInline):
    model = Shipment
    extra = 0
    readonly_fields = ('shipped_date', 'status')
    can_delete = False

# ===================================================================
# সেলস অর্ডার অ্যাডমিন (Sales Order Admin)
# ===================================================================

@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    inlines = [SalesOrderItemInline, SalesPaymentInline, ShipmentInline]
    
    list_display = ('sales_order_number', 'customer', 'warehouse', 'order_date', 'status', 'payment_status', 'get_total_amount', 'get_total_paid')
    list_filter = ('status', 'payment_status', 'warehouse', 'order_date')
    search_fields = ('sales_order_number', 'customer__name', 'user__username')
    list_per_page = 20

    # Readonly fields থেকে 'total_paid' এবং 'change_due' বাদ দেওয়া হয়েছে কারণ এগুলো মেথড
    readonly_fields = ('sales_order_number', 'created_at', 'updated_at', 'total_amount', 'get_total_paid')

    fieldsets = (
        ('Order Information', {
            'fields': ('sales_order_number', 'customer', 'warehouse', 'status', 'order_date', 'expected_delivery_date')
        }),
        ('Financials', {
            'fields': ('total_amount', 'discount', 'tax_amount', 'shipping_cost', 'round_off_amount', 'get_total_paid', 'payment_status')
        }),
        ('Legacy Payment Info', {
            'fields': ('selected_payment_method', 'payment_note'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'user'),
            'classes': ('collapse',),
        }),
    )

    # কাস্টম মেথড যা 'total_paid' ক্যালকুলেট করবে
    def get_total_paid(self, obj):
        paid = sum(p.amount for p in obj.payments.all())
        return f"{paid:.2f}"
    get_total_paid.short_description = "Total Paid"

    def get_total_amount(self, obj):
        return f"{obj.total_amount:.2f}"
    get_total_amount.short_description = "Total Amount"

# ===================================================================
# সেলস রিটার্ন অ্যাডমিন (Sales Return Admin)
# ===================================================================

class SalesReturnItemInline(admin.TabularInline):
    model = SalesReturnItem
    extra = 0
    # 'lot_sold_from' রাখা হয়েছে কারণ রিটার্ন আইটেমে এটি এখনো আছে
    readonly_fields = ('product', 'quantity', 'unit_price', 'subtotal', 'lot_sold_from')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    inlines = [SalesReturnItemInline]
    
    # 'customer' এবং 'total_amount' এরর ফিক্স
    list_display = ('id', 'get_sales_order', 'warehouse', 'return_date', 'return_type', 'total_refund_amount')
    list_filter = ('warehouse', 'return_date', 'return_type')
    search_fields = ('id', 'sales_order__sales_order_number')
    
    # Readonly fields আপডেট করা হয়েছে
    readonly_fields = ('id', 'return_date', 'total_refund_amount')

    def get_sales_order(self, obj):
        return obj.sales_order.sales_order_number if obj.sales_order else "N/A"
    get_sales_order.short_description = "Sales Order"

# ===================================================================
# পেমেন্ট এবং শিপমেন্ট রেজিস্টার (Optional)
# ===================================================================

@admin.register(SalesPayment)
class SalesPaymentAdmin(admin.ModelAdmin):
    list_display = ('sales_order', 'amount', 'payment_method', 'payment_date', 'recorded_by')
    list_filter = ('payment_date', 'payment_method')

@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'sales_order', 'warehouse', 'status', 'shipped_date')
    list_filter = ('status', 'warehouse')