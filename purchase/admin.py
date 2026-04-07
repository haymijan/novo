# purchase/admin.py

from django.contrib import admin
# === PurchaseReturn এবং PurchaseReturnItem এখানে ইম্পোর্ট করুন ===
from .models import ProductSupplier, PurchaseOrder, PurchaseOrderItem, PurchaseReturn, PurchaseReturnItem, SupplierCreditNote
# =============================================================

# PurchaseOrderItem কে PurchaseOrder এর ইনলাইন হিসেবে যোগ করা হয়েছে
class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    fields = ('product', 'quantity', 'unit_price')
    raw_id_fields = ('product',)

# PurchaseOrder মডেলকে Django অ্যাডমিন প্যানেলে রেজিস্টার করা হয়েছে।
@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'supplier', 'order_date', 'expected_delivery_date', 'status', 'total_amount')
    list_filter = ('status', 'supplier', 'order_date')
    search_fields = ('id', 'supplier__name')
    inlines = [PurchaseOrderItemInline]
    readonly_fields = ('total_amount',)

# ProductSupplier মডেলকে Django অ্যাডমিন প্যানেলে রেজিস্টার করা হয়েছে।
@admin.register(ProductSupplier)
class ProductSupplierAdmin(admin.ModelAdmin):
    list_display = ('product', 'supplier', 'supplier_product_code', 'price')
    list_filter = ('supplier', 'product__category')
    search_fields = ('product__name', 'supplier__name', 'supplier_product_code')

# ==================== নতুন কোড ব্লক শুরু ====================
# PurchaseReturnItem কে PurchaseReturn এর ইনলাইন হিসেবে দেখানো হবে
class PurchaseReturnItemInline(admin.TabularInline):
    model = PurchaseReturnItem
    extra = 0
    raw_id_fields = ('product', 'lot_serial',)

@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'supplier', 'warehouse', 'return_date', 'status', 'user')
    list_filter = ('status', 'return_date', 'warehouse')
    search_fields = ('id', 'supplier__name', 'warehouse__name')
    inlines = [PurchaseReturnItemInline]
# ===================== নতুন কোড ব্লক শেষ =====================

@admin.register(SupplierCreditNote)
class SupplierCreditNoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'supplier', 'created_date', 'amount', 'amount_available', 'status', 'purchase_return', 'applied_payment')
    list_filter = ('status', 'supplier', 'created_date')
    search_fields = ('id', 'supplier__name', 'notes')
    list_editable = ('status',) # স্ট্যাটাস অ্যাডমিন থেকে পরিবর্তন করার সুবিধা
    raw_id_fields = ('supplier', 'purchase_return', 'applied_payment') # ForeignKey ফিল্ডগুলোর জন্য সার্চ বাটন