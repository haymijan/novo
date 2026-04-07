# products/admin.py

from django.contrib import admin
from django.utils.html import format_html
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from import_export.admin import ImportExportModelAdmin
from .models import Category, UnitOfMeasureCategory, UnitOfMeasure, Product, Brand
from django.db.models import Sum
from django.db.models.functions import Coalesce

# --- Product Resource (Advanced Import Logic) ---
class ProductResource(resources.ModelResource):
    # ক্যাটাগরি এবং ব্র্যান্ড নাম দিয়ে ইম্পোর্ট করার জন্য ForeignKeyWidget ব্যবহার করা হয়েছে
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(Category, field='name')
    )
    brand = fields.Field(
        column_name='brand',
        attribute='brand',
        widget=ForeignKeyWidget(Brand, field='name')
    )
    
    class Meta:
        model = Product
        # যেসব ফিল্ড ইম্পোর্ট/এক্সপোর্ট করা যাবে
        fields = (
            'id', 'name', 'product_code', 'category', 'brand', 
            'price', 'cost_price', 'sale_price', 
            'min_stock_level', 'tracking_method', 'description', 'is_active'
        )
        # আইডি থাকলে আপডেট হবে, না থাকলে নতুন তৈরি হবে
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

# --- Admin Views ---

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'created_at') # parent যোগ করা হয়েছে
    search_fields = ('name',)
    list_filter = ('parent',)

@admin.register(UnitOfMeasureCategory)
class UnitOfMeasureCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')

@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_code', 'category', 'ratio', 'is_base_unit')
    list_filter = ('category', 'is_base_unit')

@admin.register(Product)
class ProductAdmin(ImportExportModelAdmin):
    resource_class = ProductResource
    
    # লিস্ট ভিউতে স্টক দেখানোর লজিক
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # এখানে স্টক ক্যালকুলেট করা হচ্ছে যাতে N+1 সমস্যা না হয়
        return qs.annotate(
            _total_quantity=Coalesce(Sum('stocks__quantity'), 0)
        )

    def get_total_quantity(self, obj):
        return obj._total_quantity
    get_total_quantity.short_description = 'Total Stock'
    get_total_quantity.admin_order_field = '_total_quantity'

    def get_barcode_image_tag(self, obj):
        return obj.barcode_image_tag
    get_barcode_image_tag.short_description = 'Barcode'

    list_display = ('name', 'product_code', 'brand', 'category', 'sale_price', 'get_total_quantity', 'is_active')
    list_filter = ('category', 'brand', 'is_active')
    search_fields = ('name', 'product_code', 'brand__name')
    readonly_fields = ('get_total_quantity', 'get_barcode_image_tag')
    
    fieldsets = (
        ('Basic Info', {'fields': ('name', 'product_code', 'category', 'brand', 'description', 'image')}),
        ('Pricing & Stock', {'fields': ('price', 'cost_price', 'sale_price', 'min_stock_level', 'tracking_method')}),
        ('Units', {'fields': ('unit_of_measure', 'purchase_unit_of_measure', 'sale_unit_of_measure')}),
        ('Barcode', {'fields': ('barcode', 'get_barcode_image_tag')}),
        ('Status', {'fields': ('is_active',)}),
    )