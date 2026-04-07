# accounts/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """
    Custom User Admin to display and filter by 'warehouse' and 'phone'.
    """
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Extra Information', {'fields': ('warehouse', 'phone')}),
    )
    
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Extra Information', {'fields': ('warehouse', 'phone')}),
    )

    list_display = ('username', 'email', 'phone', 'first_name', 'last_name', 'is_staff', 'warehouse')

    list_filter = BaseUserAdmin.list_filter + ('warehouse',)

    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone', 'warehouse__name')