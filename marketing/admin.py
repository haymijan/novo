from django.contrib import admin
from .models import Coupon, GiftCard


from django.utils.html import format_html
from django.urls import reverse

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_type', 'discount_value', 'valid_to', 'usage_limit', 'used_count', 'active')
    list_filter = ('active', 'discount_type', 'valid_to')
    search_fields = ('code',)

@admin.register(GiftCard)
class GiftCardAdmin(admin.ModelAdmin):
    list_display = ('code', 'initial_value', 'current_balance', 'customer', 'is_active', 'actions_buttons')
    search_fields = ('code', 'customer__name', 'customer__phone')

    def actions_buttons(self, obj):
        print_url = reverse('marketing:print_gift_card', args=[obj.pk])
        email_url = reverse('marketing:email_gift_card', args=[obj.pk])
        
        return format_html(
            '<a class="button" href="{}" target="_blank" style="background-color:#4e73df; color:white; padding:5px 10px; border-radius:4px; margin-right:5px;">Print</a>'
            '<a class="button" href="{}" style="background-color:#1cc88a; color:white; padding:5px 10px; border-radius:4px;">Email</a>',
            print_url, email_url
        )
    
    actions_buttons.short_description = 'Actions'
    actions_buttons.allow_tags = True