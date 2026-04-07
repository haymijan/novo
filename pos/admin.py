from django.contrib import admin
from .models import POSSession, POSOrder, POSOrderItem, POSOrderPayment # POSOrderPayment ইম্পোর্ট করুন

# বিদ্যমান ইনলাইন
class POSOrderItemInline(admin.TabularInline):
    model = POSOrderItem
    extra = 0
    raw_id_fields = ('product', 'lot_serial',)
    readonly_fields = ('subtotal',)

# --- নতুন ইনলাইন ---
class POSOrderPaymentInline(admin.TabularInline):
    model = POSOrderPayment
    extra = 0
    raw_id_fields = ('payment_method',)

@admin.register(POSOrder)
class POSOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'pos_session', 'warehouse', 'order_date', 'net_amount', 'total_paid') # total_paid যোগ করা হয়েছে
    list_filter = ('order_date', 'warehouse')
    inlines = [POSOrderItemInline, POSOrderPaymentInline] # নতুন ইনলাইন যোগ করা হয়েছে
    search_fields = ('id', 'pos_session__user__username', 'customer__name') # সার্চ ফিল্ড যোগ করা হলো
    raw_id_fields = ('pos_session', 'customer', 'warehouse') # ForeignKey গুলোর জন্য সার্চ বাটন

@admin.register(POSSession)
class POSSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'cash_register', 'start_time', 'end_time', 'status')
    
    # --- মূল পরিবর্তন এখানে ---
    # 'cash_register__warehouse' ফিল্টারটি বাদ দেওয়া হয়েছে
    list_filter = ('status', 'user')
    # --- পরিবর্তন শেষ ---
    
    search_fields = ('user__username', 'cash_register__name')
    raw_id_fields = ('user', 'cash_register')

# --- নতুন মডেলটি এখানে রেজিস্টার করা হয়েছে ---
@admin.register(POSOrderPayment)
class POSOrderPaymentAdmin(admin.ModelAdmin):
    list_display = ('pos_order', 'payment_method', 'amount')
    list_filter = ('payment_method',)
    raw_id_fields = ('pos_order', 'payment_method')