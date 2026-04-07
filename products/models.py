# products/models.py

from django.db import models
from io import BytesIO
from django.core.files import File
import barcode
from barcode.writer import ImageWriter
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html

#========================================================================

class Brand(models.Model):
    name = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'inventory_brand'
        ordering = ['name']


class Category(models.Model):
    name = models.CharField(max_length=200)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subcategories')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_category'
        verbose_name_plural = "Categories"
        unique_together = ('parent', 'name') 

    def __str__(self):

        full_path = [self.name]
        k = self.parent
        while k is not None:
            full_path.append(k.name)
            k = k.parent
        return ' > '.join(full_path[::-1])

    def get_all_children_ids(self):

        children_ids = [self.id]
        for child in self.subcategories.all():
            children_ids.extend(child.get_all_children_ids())
        return children_ids


class UnitOfMeasureCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "UoM Categories"


class UnitOfMeasure(models.Model):
    name = models.CharField(max_length=100, unique=True)
    short_code = models.CharField(max_length=20)
    category = models.ForeignKey(UnitOfMeasureCategory, on_delete=models.CASCADE, related_name='units')
    ratio = models.DecimalField(max_digits=10, decimal_places=5, default=1.0)
    is_base_unit = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.short_code})"

    class Meta:
        verbose_name_plural = "Units of Measure"


class Product(models.Model):
    STATUS_CHOICES = [
        ('in_stock', 'In Stock'),
        ('low_stock', 'Low Stock'),
        ('out_of_stock', 'Out of Stock'),
    ]

    TRACKING_METHOD_CHOICES = [
        ('none', 'No Tracking'),
        ('lot', 'By Lot'),
        ('serial', 'By Serial Number'),
    ]

    PRODUCT_TYPE_CHOICES = [
        ('standard', 'Standard Product'),
        ('service', 'Service'),
        ('gift_card', 'Gift Card'), 
    ]

    name = models.CharField(max_length=200, unique=True, db_index=True)

    product_code = models.CharField(max_length=100, unique=True, blank=True, null=True, verbose_name="Product Code/SKU", db_index=True)
    
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    description = models.TextField(blank=True, null=True)
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Purchase Price")
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Units
    unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.SET_NULL, null=True, blank=True, related_name='product_default_uom')
    purchase_unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.SET_NULL, null=True, blank=True, related_name='product_purchase_uom')
    sale_unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.SET_NULL, null=True, blank=True, related_name='product_sale_uom')
    
    # Stock Settings
    min_stock_level = models.PositiveIntegerField(default=10)
    tracking_method = models.CharField(max_length=20, choices=TRACKING_METHOD_CHOICES, default='none')
    
    # Media
    image = models.ImageField(upload_to='product_images/', blank=True, null=True)
    barcode = models.ImageField(upload_to='barcodes/', blank=True, null=True)
    
    # Status & Timestamps
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Product Type
    product_type = models.CharField(
        max_length=20, 
        choices=PRODUCT_TYPE_CHOICES, 
        default='standard',
        verbose_name="Product Type",
        help_text="Select 'Gift Card' if this product generates a voucher code."
    )
    
    # Gift Card Value
    gift_card_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        verbose_name="Gift Card Value",
        help_text="Only applicable if product type is Gift Card. This is the balance the customer gets."
    )

    def clean(self):
        if self.product_type == 'standard' and self.cost_price <= 0:
            raise ValidationError({
                'cost_price': "Standard products must have a valid Cost Price greater than 0."
            })
        if self.product_type in ['gift_card', 'service']:
            pass
        super().clean()

    @property
    def barcode_image_tag(self):
        if self.barcode and hasattr(self.barcode, 'url'):
            return format_html('<img src="{}" height="50px" />', self.barcode.url)
        return "No Barcode"

    def __str__(self):
        if self.product_code:
            return f"{self.name} ({self.product_code})"
        return self.name

    def save(self, *args, **kwargs):

        if not self.barcode and self.product_code:
            try:
                Code128 = barcode.get_barcode_class('code128')
                code = Code128(self.product_code, writer=ImageWriter())
                buffer = BytesIO()
                code.write(buffer)
                self.barcode.save(f'{self.product_code}.png', File(buffer), save=False)
            except Exception as e:
                print(f"Error generating barcode for {self.product_code}: {e}")

        super().save(*args, **kwargs)